# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""First-audio latency harness: pre-answer stages, statistics and alignment."""
from __future__ import annotations

import asyncio
import json
import queue
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from src.config.schema import Config
from src.server.reply_streaming.latency_baseline import (
    CATEGORIES,
    FIXTURES,
    TARGETS,
    align_turn,
    build_latency_report,
    build_turn_record,
    fixtures_from_json,
    is_active_audio,
    turn_plan,
    voiced_end_sample,
)
from src.server.reply_streaming.metrics import (
    STAGE_NAMES,
    TurnMetrics,
    observe_stages,
    timed_stage,
)
from src.server.voice_session import VoiceTurnSession


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class PreAnswerStageMetricsTests(unittest.TestCase):
    def test_pre_answer_stages_are_fixed_names(self):
        for stage in ("pre_answer", "routing", "retrieval", "model_info"):
            self.assertIn(stage, STAGE_NAMES)

    def test_prompt_accepted_latency_is_reported_beside_first_audio(self):
        clock = FakeClock()
        metrics = TurnMetrics("turn", clock=clock)
        metrics.mark_speech_end()
        clock.advance(0.5)
        metrics.mark_prompt_accepted()
        clock.advance(0.25)
        metrics.mark_prompt_accepted()
        clock.advance(1.0)
        metrics.mark_first_audio()

        snapshot = metrics.snapshot()
        self.assertEqual(snapshot["first_audio_seconds"], 1.75)
        self.assertEqual(snapshot["prompt_first_audio_seconds"], 1.25)

    def test_timed_stage_reports_to_the_observer_of_this_context_only(self):
        reported = []
        with timed_stage("model_info"):
            pass  # no observer: nothing to report, nothing raised
        with observe_stages(lambda stage, seconds: reported.append((stage, seconds))):
            with timed_stage("model_info"):
                pass
        with timed_stage("model_info"):
            pass
        self.assertEqual([stage for stage, _ in reported], ["model_info"])
        self.assertGreaterEqual(reported[0][1], 0.0)

    def test_timed_stage_reports_even_when_the_work_fails(self):
        reported = []
        with observe_stages(lambda stage, seconds: reported.append(stage)):
            with self.assertRaises(RuntimeError):
                with timed_stage("model_info"):
                    raise RuntimeError("preflight failed")
        self.assertEqual(reported, ["model_info"])

    def test_timed_stage_rejects_unknown_names(self):
        with self.assertRaises(ValueError):
            with timed_stage("transcript"):
                pass

    def test_llamacpp_model_info_preflight_is_timed(self):
        from src.llm.engines.openai import OpenAILLM

        config = Config()
        config.llm.provider = "llamacpp"
        engine = OpenAILLM(config, api_key="test")
        completion = MagicMock()
        completion.__iter__.return_value = iter([SimpleNamespace(
            usage=None,
            choices=[SimpleNamespace(delta=SimpleNamespace(content="回答。"), finish_reason="stop")],
        )])
        engine._client = MagicMock()
        engine._client.chat.completions.create.return_value = completion
        reported = []

        def preflight(*_args, **_kwargs):
            reported.append("preflight-running")
            return {"over_capacity": False, "estimated": True}

        with patch("src.llm.engines.openai.measure_request", side_effect=preflight):
            with observe_stages(lambda stage, _seconds: reported.append(stage)):
                list(engine.chat_stream("問題"))
        self.assertEqual(reported, ["preflight-running", "model_info"])


class _Avatar:
    def __init__(self):
        self.messages = []

    def put_msg_txt(self, text, data=None):
        self.messages.append((text, data))

    def flush_talk(self):
        pass

    def configure_media_fence(self, **_kwargs):
        pass


class _Roles:
    """Routing that decides once the test opens ``gate`` (ADR 0022: concurrent)."""

    enabled = True

    def __init__(self, clock: FakeClock, seconds: float, plan: dict) -> None:
        self.clock = clock
        self.seconds = seconds
        self.plan = plan
        self.continuations: dict = {}
        self.gate = asyncio.Event()

    def continues(self, _voice, _turn_id):
        return False

    def speculative_plan(self):
        return {"context": ""}

    async def before_generate(self, _voice, _text, _turn_id, _generation):
        await self.gate.wait()
        self.clock.advance(self.seconds)
        return dict(self.plan)

    def cancel(self, _sid):
        pass

    def input_allowed(self, _voice):
        return True

    def notify(self, _session=None):
        pass


class VoiceSessionPreAnswerStageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.avatar = _Avatar()
        config = SimpleNamespace(
            model=SimpleNamespace(avatar_id="alpha"),
            asr=SimpleNamespace(type="whisper", model_size="base", language="zh"),
            vad=SimpleNamespace(),
            reply_streaming=SimpleNamespace(enabled=False),
            profile_rag={"enabled": True, "dataset_ids": ["a" * 32]},
        )
        self.session = VoiceTurnSession(94, config, self.avatar, clock=self.clock)
        self.session._segmenter = SimpleNamespace(reset=lambda: None, is_speaking=False)
        self.events = []
        self.session.attach_event_sink(lambda raw: self.events.append(json.loads(raw)))

    async def asyncTearDown(self):
        await self.session.close()

    async def _run_turn(self, roles, text):
        """Retrieval 0.1 s, answer preflight 0.2 s, then routing decides."""
        self.session._role_coordinator = roles
        clock = self.clock
        llm_started = threading.Event()

        async def retrieve(_client, _question, _dataset_ids, **_kwargs):
            clock.advance(0.1)
            return {"status": "empty", "sources": []}

        def fake_llm(_text, _avatar, **_kwargs):
            # The engine's preflight runs inside the LLM worker thread.
            clock.advance(0.2)
            with timed_stage("model_info"):
                pass
            llm_started.set()
            return "回答。"

        with patch("src.server.voice_session.llm_response", side_effect=fake_llm), patch(
            "src.server.voice_session.RagFlowClient.retrieve", retrieve
        ), patch("src.server.voice_session.prepare_spoken_history"):
            await self.session.start_text_turn(text, interrupt=False)
            self.assertTrue(await asyncio.to_thread(llm_started.wait, 2))
            await asyncio.sleep(0)  # deliver the thread-safe model_info callback
            roles.gate.set()
            await self.session._turn_task
            await asyncio.sleep(0)

    async def test_routing_runs_beside_retrieval_and_the_answer(self):
        await self._run_turn(_Roles(self.clock, 0.4, {"context": ""}), "問題")
        self.clock.advance(0.05)
        self.session.on_output_audio(True)

        snapshot = self.session.metrics_snapshot()
        stages = snapshot["stage_seconds"]
        self.assertEqual(stages["retrieval"], 0.1)
        self.assertEqual(stages["pre_answer"], 0.1, "the answer does not wait for routing")
        self.assertEqual(stages["routing"], 0.7)
        self.assertEqual(stages["routing_hold"], 0.0)
        self.assertIsNotNone(stages["model_info"])
        self.assertEqual(snapshot["prompt_first_audio_seconds"], 0.75)
        self.assertEqual(snapshot["first_audio_seconds"], 0.75)

    async def test_fixed_reply_ends_pre_answer_and_forgets_the_discarded_answer(self):
        await self._run_turn(
            _Roles(self.clock, 0.3, {"fixed": "接下來請天氣助手為您說明。"}), "明天會下雨嗎")
        self.assertEqual([text for text, _ in self.avatar.messages], ["接下來請天氣助手為您說明。"])
        stages = self.session.metrics_snapshot()["stage_seconds"]
        self.assertEqual(stages["routing"], 0.6)
        self.assertEqual(stages["pre_answer"], 0.6)
        self.assertEqual(stages["retrieval"], 0.1)
        self.assertIsNone(stages["model_info"])
        self.assertIsNone(stages["llm_first_token"])


class VideoEnqueueStageTests(unittest.TestCase):
    """Idle frames carry an avatar_epoch eventpoint; they are not reply video."""

    def _avatar(self, marks):
        from src.avatars.base import BaseAvatar

        avatar = BaseAvatar.__new__(BaseAvatar)
        avatar.config = SimpleNamespace(sessionid=7, video=SimpleNamespace(max_height=0))
        avatar.res_frame_queue = queue.Queue()
        avatar.frame_list_cycle = [np.zeros((32, 32, 3), dtype=np.uint8)]
        avatar.custom_index = {}
        avatar.custom_img_cycle = {}
        avatar.speaking = False
        avatar._asset_epoch = 3
        avatar.accepts_media = lambda *_a: True
        avatar.mark_stage_end = marks.append
        avatar.paste_back_frame = lambda _frame, _idx: np.zeros((32, 32, 3), np.uint8)
        avatar.record_audio_data = lambda _frame: None
        avatar.record_video_data = lambda _frame: None
        return avatar

    def _run(self, avatar, batches):
        quit_event = threading.Event()
        seen = []

        class Track:
            async def enqueue(self, frame, eventpoint=None):
                if hasattr(frame, "width"):  # video frames only
                    seen.append(eventpoint)
                    if len(seen) == len(batches):
                        quit_event.set()
                return True

        for batch in batches:
            avatar.res_frame_queue.put(batch)

        async def run():
            await asyncio.wait_for(asyncio.to_thread(
                avatar._process_frames_loop, quit_event,
                asyncio.get_running_loop(), Track(), Track()), 5)

        asyncio.run(run())

    def test_idle_frames_do_not_complete_video_enqueue(self):
        marks: list[str] = []
        avatar = self._avatar(marks)
        idle = [(np.zeros(320, np.float32), 1, None)] * 2
        self._run(avatar, [(np.zeros((32, 32, 3), np.uint8), 0, idle, 3)])
        self.assertNotIn("webrtc_video_enqueue", marks)

    def test_reply_frames_complete_video_enqueue(self):
        marks: list[str] = []
        avatar = self._avatar(marks)
        idle = [(np.zeros(320, np.float32), 1, None)] * 2
        reply_event = {"turn_id": "t", "generation": 1, "fragment_sequence": 0}
        speech = [(np.zeros(320, np.float32), 0, reply_event)] * 2
        frame = np.zeros((32, 32, 3), np.uint8)
        self._run(avatar, [(frame, 0, idle, 3), (frame, 0, speech, 3)])
        self.assertEqual(marks.count("webrtc_video_enqueue"), 1)
        self.assertLess(marks.index("avatar_pasteback_done"), marks.index("webrtc_video_enqueue"))


class FixtureSetTests(unittest.TestCase):
    def test_each_category_has_ten_utterances_in_both_languages(self):
        for category in CATEGORIES:
            items = [f for f in FIXTURES if f.category == category]
            self.assertGreaterEqual(len(items), 10, category)
            self.assertEqual({f.language for f in items}, {"zh-TW", "en-US"}, category)
        self.assertEqual(len({f.fixture_id for f in FIXTURES}), len(FIXTURES))

    def test_every_handoff_utterance_is_part_of_a_forward_then_return_pair(self):
        plan = turn_plan(FIXTURES)
        for index, fixture in enumerate(plan):
            if fixture.handoff == "to_specialist":
                self.assertEqual(plan[index + 1].handoff, "to_main")
            if fixture.handoff == "to_main":
                self.assertEqual(plan[index - 1].handoff, "to_specialist")
        self.assertEqual(sorted(f.fixture_id for f in plan), sorted(f.fixture_id for f in FIXTURES))

    def test_plan_interleaves_categories_and_repeats_rounds(self):
        plan = turn_plan(FIXTURES, rounds=2)
        self.assertEqual(len(plan), 2 * len(FIXTURES))
        self.assertEqual({f.category for f in plan[:4]}, set(CATEGORIES))

    def test_site_fixtures_replace_the_builtin_set(self):
        fixtures = fixtures_from_json(json.dumps([
            {"id": "kb-1", "category": "rag", "language": "zh-TW", "text": "門票多少錢？"},
            {"id": "w-1", "category": "handoff", "language": "zh-TW",
             "text": "明天臺北會下雨嗎？", "handoff": "to_specialist"},
            {"id": "w-2", "category": "handoff", "language": "en-US",
             "text": "Tell me a fun fact.", "handoff": "to_main"},
        ]))
        self.assertEqual([f.fixture_id for f in fixtures], ["kb-1", "w-1", "w-2"])
        with self.assertRaises(ValueError):
            fixtures_from_json(json.dumps([{"id": "x", "category": "other",
                                            "language": "zh-TW", "text": "t"}]))
        with self.assertRaises(ValueError):
            fixtures_from_json(json.dumps([{"id": "x", "category": "handoff",
                                            "language": "zh-TW", "text": "t",
                                            "handoff": "to_specialist"}]))


class RecordingSignalTests(unittest.TestCase):
    def test_voiced_end_ignores_leading_and_trailing_silence(self):
        rate = 16000
        tone = (0.3 * 32767 * np.sin(np.arange(int(0.5 * rate)) / 5)).astype(np.int16)
        samples = np.concatenate((np.zeros(int(0.2 * rate), np.int16), tone,
                                  np.zeros(int(0.9 * rate), np.int16)))
        end = voiced_end_sample(samples)
        self.assertAlmostEqual(end / rate, 0.7, delta=0.021)

    def test_voiced_end_rejects_a_silent_recording(self):
        with self.assertRaises(ValueError):
            voiced_end_sample(np.zeros(16000, np.int16))

    def test_reply_audio_activity_uses_a_peak_threshold(self):
        self.assertFalse(is_active_audio(np.zeros((1, 1920), np.int16)))
        self.assertFalse(is_active_audio(np.full((1, 1920), 20, np.int16)))
        self.assertTrue(is_active_audio(np.full((1, 1920), 900, np.int16)))


def _server(first_audio=1.5, **stages):
    base = {name: None for name in STAGE_NAMES}
    base.update({"vad_endpoint": 0.32, "asr": 0.4, "pre_answer": 0.5,
                 "first_fragment": 0.3, "avatar_to_webrtc_commit": 0.25})
    base.update(stages)
    return {"first_audio_seconds": first_audio, "prompt_first_audio_seconds": first_audio - 0.42,
            "stage_seconds": base}


class AlignmentTests(unittest.TestCase):
    def test_sequential_chain_explains_first_audio(self):
        aligned = align_turn(_server(1.5), perceived_first_audio_seconds=1.92)
        self.assertEqual(aligned["chain_seconds"], 1.45)
        self.assertEqual(aligned["server_residual_seconds"], 0.05)
        self.assertEqual(aligned["server_perceived_first_audio_seconds"], 1.82)
        self.assertEqual(aligned["client_offset_seconds"], 0.1)
        self.assertTrue(aligned["aligned"])

    def test_fixed_reply_has_no_fragment_stage(self):
        aligned = align_turn(_server(1.2, first_fragment=None), perceived_first_audio_seconds=1.6)
        self.assertEqual(aligned["chain_seconds"], 1.15)
        self.assertTrue(aligned["aligned"])

    def test_text_turn_has_no_asr_or_vad_stage(self):
        aligned = align_turn(_server(1.1, asr=None, vad_endpoint=None),
                             perceived_first_audio_seconds=None)
        self.assertEqual(aligned["chain_seconds"], 1.05)
        self.assertIsNone(aligned["server_perceived_first_audio_seconds"])
        self.assertFalse(aligned["aligned"])

    def test_audio_heard_before_the_server_could_answer_is_misattributed(self):
        # e.g. an idle greeting still in flight when the recording ended
        aligned = align_turn(_server(1.5), perceived_first_audio_seconds=0.4)
        self.assertFalse(aligned["aligned"])

    def test_audio_far_later_than_the_server_commit_is_misaligned(self):
        aligned = align_turn(_server(1.5), perceived_first_audio_seconds=3.5)
        self.assertFalse(aligned["aligned"])


def _turn(category, perceived, first_audio, **extra):
    record = {
        "fixture_id": f"{category}-{perceived}", "category": category, "language": "zh-TW",
        "status": "completed", "perceived_first_audio_seconds": perceived,
        **_server(first_audio), **extra,
    }
    record["alignment"] = align_turn(record, perceived_first_audio_seconds=perceived)
    return record


class LatencyReportTests(unittest.TestCase):
    def setUp(self):
        self.turns = [
            _turn("general", 1.0, 0.6), _turn("general", 2.0, 1.6), _turn("general", 3.0, 2.6),
            _turn("rag", 1.5, 1.1), _turn("rag", 0.1, 1.1),  # second: misattributed audio
            _turn("handoff", 1.5, 1.1, handoff_observed=True, specialist_first_audio_seconds=1.3),
            {"fixture_id": "general-x", "category": "general", "language": "en-US",
             "status": "timeout"},
        ]
        self.report = build_latency_report(self.turns, environment={"gpu": "test"})

    def test_percentiles_per_category_use_aligned_turns_only(self):
        general = self.report["categories"]["general"]
        self.assertEqual(general["turns"], 3)
        self.assertEqual(general["perceived_first_audio_seconds"], {"p50": 2.0, "p95": 2.9})
        self.assertEqual(general["first_audio_seconds"]["p50"], 1.6)
        rag = self.report["categories"]["rag"]
        self.assertEqual(rag["perceived_first_audio_seconds"], {"p50": 1.5, "p95": 1.5})
        self.assertEqual(rag["misaligned_turns"], 1)
        self.assertEqual(self.report["categories"]["all"]["turns"], 6)

    def test_every_stage_has_p50_and_p95(self):
        stages = self.report["categories"]["all"]["stage_seconds"]
        self.assertEqual(set(stages), set(STAGE_NAMES))
        self.assertEqual(stages["asr"], {"p50": 0.4, "p95": 0.4})
        self.assertEqual(stages["routing"], {"p50": None, "p95": None})

    def test_failed_turns_and_targets_are_reported(self):
        self.assertEqual(self.report["failed_turns"], 1)
        self.assertEqual(self.report["categories"]["general"]["failed_turns"], 1)
        self.assertEqual(self.report["targets"], TARGETS)
        checks = self.report["categories"]["general"]["checks"]
        self.assertFalse(checks["phase1"])
        self.assertTrue(self.report["categories"]["handoff"]["checks"]["phase1"])
        self.assertEqual(
            self.report["categories"]["handoff"]["specialist_first_audio_seconds"]["p50"], 1.3)

    def test_report_is_content_free(self):
        serialized = json.dumps(self.report, ensure_ascii=False)
        for forbidden in ("text", "transcript", "assistant_response", "audio\""):
            self.assertNotIn(f'"{forbidden}', serialized)


class TurnRecordTests(unittest.TestCase):
    def test_record_keeps_scalar_metrics_and_drops_turn_identity(self):
        fixture = FIXTURES[0]
        event = {"turn_id": "abc123", "terminal_reason": "completed",
                 "metrics": {"turn_id": "abc123", **_server(1.5)}}
        record = build_turn_record(fixture, event, perceived_first_audio_seconds=1.9200001,
                                   rag_status="empty")
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["perceived_first_audio_seconds"], 1.92)
        self.assertTrue(record["alignment"]["aligned"])
        self.assertNotIn("abc123", json.dumps(record))

    def test_missing_metrics_is_a_failed_turn(self):
        record = build_turn_record(FIXTURES[0], None)
        self.assertEqual(record["status"], "timeout")
        report = build_latency_report([record], environment={})
        self.assertEqual(report["failed_turns"], 1)


class PushTrackMarkerTests(unittest.TestCase):
    def test_voiced_end_marker_fires_when_its_frame_is_sent(self):
        from scripts.run_voice_soak import FRAME_SAMPLES, PushAudioTrack

        async def run():
            track = PushAudioTrack()
            reported = []
            track.push(np.ones(3 * FRAME_SAMPLES, np.int16),
                       on_sample_sent=(FRAME_SAMPLES + 160, reported.append))
            await track.recv()
            self.assertEqual(reported, [])
            await track.recv()
            self.assertEqual(len(reported), 1)
            await track.recv()
            await track.recv()  # silence padding never re-fires
            self.assertEqual(len(reported), 1)

        asyncio.run(run())


class HarnessTurnFlowTests(unittest.TestCase):
    """Drive the harness turn logic with a scripted stage event stream."""

    def _peer(self):
        from scripts.measure_first_audio import LatencyPeer
        from scripts.run_voice_soak import EventBroker

        peer = LatencyPeer.__new__(LatencyPeer)
        peer.voice_ended_at = None
        peer.first_reply_audio_at = None
        peer.handoff_turns = set()
        peer.rag_status = {}
        peer._transcript_turn = None
        peer.events = EventBroker()

        def push(_samples, *, on_sample_sent):
            on_sample_sent[1](50.0)
            peer.first_reply_audio_at = 52.0

        peer.audio = SimpleNamespace(push=push)
        return peer

    @staticmethod
    def _feed(peer, events):
        for seq, event in enumerate(events, start=1):
            raw = json.dumps({**event, "seq": seq})
            peer._observe(raw)
            peer.events.receive(raw)

    def _handoff_events(self):
        return [
            {"type": "user_transcript", "turn_id": "a"},
            {"type": "role_state", "turn_id": "a", "phase": "announcement"},
            {"type": "turn_metrics", "turn_id": "a", "terminal_reason": "completed",
             "metrics": _server(1.6)},
            {"type": "state", "turn_id": None, "state": "listening"},
            {"type": "role_handoff", "turn_id": None, "source_turn_id": "a", "target_turn_id": "b"},
            {"type": "turn_metrics", "turn_id": "b", "terminal_reason": "completed",
             "metrics": _server(1.3)},
        ]

    def _measure(self, events, fixture, timeout):
        from scripts.measure_first_audio import measure_turn

        async def run():
            peer = self._peer()  # EventBroker's queue belongs to this loop
            self._feed(peer, events)
            return await measure_turn(peer, fixture, np.zeros(320, np.int16), 0,
                                      timeout=timeout)

        return asyncio.run(run())

    def test_handoff_turn_waits_for_listening_after_the_specialist_reply(self):
        fixture = next(f for f in FIXTURES if f.handoff == "to_specialist")
        with self.assertRaises(asyncio.TimeoutError):
            # only a stale listening event so far
            self._measure(self._handoff_events(), fixture, 0.2)

        record = self._measure([*self._handoff_events(),
                                {"type": "state", "turn_id": None, "state": "listening"}],
                               fixture, 1.0)
        self.assertTrue(record["handoff_observed"])
        self.assertEqual(record["first_audio_seconds"], 1.6)
        self.assertEqual(record["specialist_first_audio_seconds"], 1.3)
        self.assertEqual(record["perceived_first_audio_seconds"], 2.0)
        self.assertTrue(record["alignment"]["aligned"])

    def test_plain_turn_records_retrieval_status(self):
        fixture = next(f for f in FIXTURES if f.category == "rag")
        record = self._measure([
            {"type": "user_transcript", "turn_id": "c"},
            {"type": "rag_retrieval", "turn_id": "c", "status": "matched"},
            {"type": "turn_metrics", "turn_id": "c", "terminal_reason": "completed",
             "metrics": _server(1.6)},
            {"type": "state", "turn_id": "c", "state": "listening"},
        ], fixture, 1.0)
        self.assertFalse(record["handoff_observed"])
        self.assertEqual(record["rag_status"], "matched")
        self.assertIsNone(record["specialist_first_audio_seconds"])
