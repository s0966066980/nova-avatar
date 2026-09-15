import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import numpy as np

from src.server.reply_streaming.circuit_breaker import ReplyCircuitBreaker
from src.server.voice_session import OUTPUT_STALL_FRAMES, VoiceTurnSession


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeAvatar:
    def __init__(self):
        self.on_fragment_queued = None
        self.on_fragment_failed = None
        self.flush_count = 0

    def configure_media_fence(
        self,
        *,
        media_guard,
        on_stale_drop,
        on_fragment_queued=None,
        on_fragment_failed=None,
        **_unused,
    ):
        self.media_guard = media_guard
        self.on_stale_drop = on_stale_drop
        self.on_fragment_queued = on_fragment_queued
        self.on_fragment_failed = on_fragment_failed

    def flush_talk(self):
        self.flush_count += 1

    def is_speaking(self):
        return False


class PlaybackCommitTests(unittest.IsolatedAsyncioTestCase):
    def make_session(self):
        config = SimpleNamespace(
            asr=SimpleNamespace(type="whisper", model_size="base", language="zh"),
            vad=SimpleNamespace(),
            reply_streaming=SimpleNamespace(enabled=True),
        )
        avatar = FakeAvatar()
        session = VoiceTurnSession(9, config, avatar)
        events = []
        session.attach_event_sink(lambda raw: events.append(json.loads(raw)))
        session._turn_id = "turn-1"
        session._start_turn_context("turn-1")
        return session, avatar, events

    async def test_subtitle_and_played_fragment_commit_on_first_non_silent_frame(self):
        session, avatar, events = self.make_session()
        metadata = {
            "turn_id": "turn-1",
            "generation": 0,
            "fragment_sequence": 2,
        }
        avatar.on_fragment_queued("尚未播放", metadata)

        session.on_output_audio_frame(metadata, False)
        self.assertNotIn("assistant_fragment", [event["type"] for event in events])

        session.on_output_audio_frame(metadata, True)
        session.on_output_audio_frame(metadata, True)

        commits = [event for event in events if event["type"] == "assistant_fragment"]
        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0]["text"], "尚未播放")
        self.assertEqual(session.played_assistant_text, "尚未播放")
        await session.close()

    async def test_fragment_end_is_emitted_only_after_its_last_audio_frame(self):
        session, avatar, events = self.make_session()
        metadata = {
            "turn_id": "turn-1",
            "generation": 0,
            "fragment_sequence": 0,
            "fragment_end": True,
        }
        avatar.on_fragment_queued("第一句。", metadata)

        session.on_output_audio_frame(metadata, True)

        kinds = [event["type"] for event in events]
        self.assertLess(kinds.index("assistant_fragment"), kinds.index("assistant_fragment_end"))
        await session.close()

    async def test_interrupt_commits_user_and_only_fragments_that_reached_playback(self):
        session, avatar, _ = self.make_session()
        first = {"turn_id": "turn-1", "generation": 0, "fragment_sequence": 0}
        second = {"turn_id": "turn-1", "generation": 0, "fragment_sequence": 1}
        avatar.on_fragment_queued("已播放。", first)
        avatar.on_fragment_queued("未播放。", second)
        session.on_output_audio_frame(first, True)

        with (
            patch(
                "src.server.voice_session.commit_session_history",
                return_value=True,
            ) as commit,
            patch("src.server.voice_session.asyncio.sleep", new=AsyncMock()),
        ):
            await session.interrupt()

        commit.assert_called_once_with(
            9,
            "turn-1",
            assistant_text="已播放。",
            terminal_reason="interrupt",
        )
        await session.close()

    async def test_interrupt_metrics_are_emitted_after_output_stops_and_listening_resumes(self):
        session, _, events = self.make_session()
        session._turn_id = "turn-1"
        session._start_turn_context("turn-1")
        session._metrics.mark_speech_end()
        session.on_output_audio(True)

        with patch("src.server.voice_session.asyncio.sleep", new=AsyncMock()):
            await session.interrupt()

        metric_event = next(event for event in events if event["type"] == "turn_metrics")
        self.assertIsNotNone(metric_event["metrics"]["interrupt_stop_seconds"])
        self.assertIsNotNone(metric_event["metrics"]["listening_resume_seconds"])
        self.assertLess(
            next(i for i, event in enumerate(events) if event["type"] == "state" and event["state"] == "listening"),
            events.index(metric_event),
        )
        await session.close()

    async def test_stale_frame_cannot_commit_subtitle_or_history(self):
        session, avatar, events = self.make_session()
        metadata = {"turn_id": "turn-1", "generation": 0, "fragment_sequence": 0}
        avatar.on_fragment_queued("舊內容", metadata)
        session._generation = 1

        session.on_output_audio_frame(metadata, True)

        self.assertNotIn("assistant_fragment", [event["type"] for event in events])
        self.assertEqual(session.played_assistant_text, "")
        await session.close()

    async def test_silence_between_fragments_does_not_finish_or_commit_turn(self):
        session, avatar, events = self.make_session()
        first = {
            "turn_id": "turn-1",
            "generation": 0,
            "fragment_sequence": 0,
            "fragment_end": True,
        }
        second = {
            "turn_id": "turn-1",
            "generation": 0,
            "fragment_sequence": 1,
        }
        avatar.on_fragment_queued("第一句。", first)
        avatar.on_fragment_queued("第二句。", second)
        session._llm_finished = True
        session.on_output_audio_frame(first, True)
        session.on_output_audio(True)

        with patch("src.server.voice_session.commit_session_history") as commit:
            session.on_output_audio(False)
            session.on_output_audio(False)
            session.on_output_audio(False)
            await asyncio.sleep(0)

        commit.assert_not_called()
        self.assertTrue(session._output_active)
        self.assertNotIn("speaking_end", [event["type"] for event in events])
        await session.close()

    async def test_missing_first_audio_fails_turn_and_commits_user_only(self):
        session, avatar, events = self.make_session()
        metadata = {
            "turn_id": "turn-1",
            "generation": 0,
            "fragment_sequence": 0,
        }
        avatar.on_fragment_queued("從未播放", metadata)
        session._llm_finished = True
        session._silent_output_frames = 49

        with patch(
            "src.server.voice_session.commit_session_history",
            return_value=True,
        ) as commit:
            session.on_output_audio(False)

        commit.assert_called_once_with(
            9,
            "turn-1",
            assistant_text="",
            terminal_reason="playback_error_before_commit",
        )
        self.assertEqual(avatar.flush_count, 1)
        error = next(event for event in events if event.get("state") == "error")
        self.assertEqual(error["error"], "playback_error_before_commit")
        self.assertIsNone(session._turn_id)
        await session.close()

    async def test_output_stall_timeout_waits_until_tts_is_no_longer_working(self):
        session, avatar, _ = self.make_session()
        metadata = {
            "turn_id": "turn-1",
            "generation": 0,
            "fragment_sequence": 0,
        }
        avatar.on_fragment_queued("仍在合成", metadata)
        avatar.tts = SimpleNamespace(has_pending_work=lambda: True)
        session._llm_finished = True
        session._silent_output_frames = 49

        with patch("src.server.voice_session.commit_session_history") as commit:
            session.on_output_audio(False)

        commit.assert_not_called()
        self.assertEqual(session._silent_output_frames, 0)
        self.assertEqual(session._turn_id, "turn-1")
        await session.close()

    async def test_output_stall_timeout_recovers_if_tts_pending_work_times_out(self):
        session, avatar, _ = self.make_session()
        metadata = {
            "turn_id": "turn-1",
            "generation": 0,
            "fragment_sequence": 0,
        }
        avatar.on_fragment_queued("仍在合成但卡住", metadata)
        avatar.tts = SimpleNamespace(has_pending_work=lambda: True)
        session._llm_finished = True

        max_tts_stall = max(
            OUTPUT_STALL_FRAMES * 4,
            session._inter_fragment_stall_frames * 2,
        )
        with patch("src.server.voice_session.commit_session_history") as commit:
            for _ in range(max_tts_stall):
                session.on_output_audio(False)

        commit.assert_called_once()
        self.assertIsNone(session._turn_id)
        await session.close()

    async def test_tts_failure_after_commit_fails_turn_without_waiting_for_watchdog(self):
        session, avatar, events = self.make_session()
        session._event_loop = asyncio.get_running_loop()
        first = {
            "turn_id": "turn-1",
            "generation": 0,
            "fragment_sequence": 0,
            "fragment_end": True,
        }
        failed = {
            "turn_id": "turn-1",
            "generation": 0,
            "fragment_sequence": 1,
        }
        avatar.on_fragment_queued("已播放。", first)
        avatar.on_fragment_queued("合成失敗。", failed)
        session.on_output_audio_frame(first, True)
        session.on_output_audio(True)

        with patch(
            "src.server.voice_session.commit_session_history",
            return_value=True,
        ) as commit:
            avatar.on_fragment_failed(failed, "tts_exhausted_before_audio")
            await asyncio.sleep(0)

        commit.assert_called_once_with(
            9,
            "turn-1",
            assistant_text="已播放。",
            terminal_reason="tts_error_after_commit",
        )
        self.assertEqual(avatar.flush_count, 1)
        error = next(event for event in events if event.get("state") == "error")
        self.assertEqual(error["error"], "tts_error_after_commit")
        metrics = next(event for event in events if event["type"] == "turn_metrics")
        self.assertEqual(metrics["terminal_reason"], "tts_error_after_commit")
        self.assertIsNone(session._turn_id)
        committed = next(event for event in events if event["type"] == "turn_committed")
        self.assertEqual(committed["turn_id"], "turn-1")
        self.assertEqual(committed["played_text"], "已播放。")
        self.assertEqual(committed["reason"], "tts_error_after_commit")
        await session.close()

    async def test_tts_failure_before_commit_emits_empty_played_text(self):
        session, avatar, events = self.make_session()
        session._event_loop = asyncio.get_running_loop()
        metadata = {
            "turn_id": "turn-1",
            "generation": 0,
            "fragment_sequence": 0,
        }
        avatar.on_fragment_queued("從未播放", metadata)

        with patch(
            "src.server.voice_session.commit_session_history",
            return_value=True,
        ):
            avatar.on_fragment_failed(metadata, "tts_exhausted_before_audio")
            await asyncio.sleep(0)

        committed = next(event for event in events if event["type"] == "turn_committed")
        self.assertEqual(committed["played_text"], "")
        self.assertEqual(committed["reason"], "tts_error_before_commit")
        await session.close()

    async def test_interrupt_emits_turn_committed_with_played_text(self):
        session, avatar, events = self.make_session()
        first = {"turn_id": "turn-1", "generation": 0, "fragment_sequence": 0}
        second = {"turn_id": "turn-1", "generation": 0, "fragment_sequence": 1}
        avatar.on_fragment_queued("已播放。", first)
        avatar.on_fragment_queued("未播放。", second)
        session.on_output_audio_frame(first, True)

        with (
            patch(
                "src.server.voice_session.commit_session_history",
                return_value=True,
            ),
            patch("src.server.voice_session.asyncio.sleep", new=AsyncMock()),
        ):
            await session.interrupt()

        committed = next(event for event in events if event["type"] == "turn_committed")
        self.assertEqual(committed["played_text"], "已播放。")
        self.assertEqual(committed["reason"], "interrupt")
        await session.close()

    async def test_history_commit_emits_turn_committed_only_once(self):
        session, _, events = self.make_session()
        with patch(
            "src.server.voice_session.commit_session_history",
            return_value=True,
        ):
            self.assertTrue(session._commit_history("completed", turn_id="turn-1"))
            self.assertFalse(session._commit_history("completed", turn_id="turn-1"))

        committed = [event for event in events if event["type"] == "turn_committed"]
        self.assertEqual(len(committed), 1)
        self.assertEqual(committed[0]["played_text"], "")
        self.assertEqual(committed[0]["reason"], "completed")
        await session.close()

    async def test_completed_turn_emits_content_free_soak_metrics(self):
        session, avatar, events = self.make_session()
        metadata = {
            "turn_id": "turn-1",
            "generation": 0,
            "fragment_sequence": 0,
            "fragment_end": True,
        }
        avatar.on_fragment_queued("已播放但不可進指標", metadata)
        session._llm_finished = True
        session.on_output_audio_frame(metadata, True)
        session.on_output_audio(True)

        with (
            patch("src.server.voice_session.commit_session_history"),
            patch("src.server.voice_session.asyncio.sleep", new=AsyncMock()),
        ):
            session.on_output_audio(False)
            session.on_output_audio(False)
            session.on_output_audio(False)
            await session._tail_task

        metric_event = next(event for event in events if event["type"] == "turn_metrics")
        self.assertEqual(metric_event["terminal_reason"], "completed")
        self.assertIn("first_audio_seconds", metric_event["metrics"])
        self.assertNotIn("已播放但不可進指標", json.dumps(metric_event, ensure_ascii=False))
        committed = next(event for event in events if event["type"] == "turn_committed")
        self.assertEqual(committed["played_text"], "已播放但不可進指標")
        self.assertEqual(committed["reason"], "completed")
        await session.close()

    async def test_registered_voice_test_receives_played_text_before_metric_event(self):
        persisted = []
        session, avatar, events = self.make_session()
        session._test_result_sink = persisted.append
        metadata = {
            "turn_id": "turn-1",
            "generation": 0,
            "fragment_sequence": 0,
            "fragment_end": True,
        }
        avatar.on_fragment_queued("實際播出的測試回答", metadata)
        session._llm_finished = True
        session.on_output_audio_frame(metadata, True)
        session.on_output_audio(True)

        with (
            patch("src.server.voice_session.commit_session_history"),
            patch("src.server.voice_session.asyncio.sleep", new=AsyncMock()),
        ):
            session.on_output_audio(False)
            session.on_output_audio(False)
            session.on_output_audio(False)
            await session._tail_task

        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0]["assistant_response"], "實際播出的測試回答")
        self.assertEqual(persisted[0]["terminal_reason"], "completed")
        metric_event = next(event for event in events if event["type"] == "turn_metrics")
        self.assertNotIn("assistant_response", metric_event)
        await session.close()


class ReplyCircuitBreakerTests(unittest.TestCase):
    def test_third_error_opens_breaker_for_next_turn_only(self):
        clock = FakeClock()
        breaker = ReplyCircuitBreaker(clock=clock)

        self.assertEqual(breaker.mode_for_next_turn(), "streaming")
        for _ in range(2):
            self.assertFalse(breaker.record_pipeline_error())
            self.assertEqual(breaker.mode_for_active_turn(), "streaming")
        self.assertTrue(breaker.record_pipeline_error())
        self.assertEqual(breaker.mode_for_active_turn(), "streaming")

        self.assertEqual(breaker.mode_for_next_turn(), "legacy")
        self.assertEqual(breaker.mode_for_active_turn(), "legacy")

    def test_old_errors_expire_and_probe_is_required_to_recover(self):
        clock = FakeClock()
        breaker = ReplyCircuitBreaker(clock=clock)
        for _ in range(3):
            breaker.record_pipeline_error()
        self.assertEqual(breaker.mode_for_next_turn(), "legacy")
        self.assertFalse(breaker.record_health_probe(False))
        self.assertEqual(breaker.mode_for_next_turn(), "legacy")
        self.assertTrue(breaker.record_health_probe(True))
        self.assertEqual(breaker.mode_for_next_turn(), "streaming")

        breaker.record_pipeline_error()
        clock.advance(301)
        breaker.record_pipeline_error()
        breaker.record_pipeline_error()
        self.assertEqual(breaker.mode_for_next_turn(), "streaming")

    def test_successful_streaming_turn_resets_consecutive_error_streak(self):
        breaker = ReplyCircuitBreaker()
        breaker.record_pipeline_error()
        breaker.record_pipeline_error()
        breaker.record_turn_success()
        breaker.record_pipeline_error()

        self.assertEqual(breaker.mode_for_next_turn(), "streaming")


class PlaybackMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_audio_track_reports_activity_with_committed_eventpoint(self):
        from src.utils.webrtc import PlayerStreamTrack

        callbacks = []

        class Player:
            def _start(self, _track):
                return None

            def _stop(self, _track):
                return None

            def notify(self, _eventpoint):
                return None

            def notify_media_timing(self, _kind, _seconds):
                return None

            def notify_audio_activity(self, _active):
                return None

            def notify_audio_frame(self, eventpoint, active):
                callbacks.append((eventpoint, active))

        eventpoint = {
            "turn_id": "turn-1",
            "generation": 0,
            "fragment_sequence": 0,
            "fragment_end": True,
        }
        frame = SimpleNamespace(
            pts=None,
            time_base=None,
            to_ndarray=lambda: np.ones((1, 320), dtype=np.int16),
        )
        player = Player()
        track = PlayerStreamTrack(player, "audio")
        await track.enqueue(frame, eventpoint)

        self.assertIs(await track.recv(), frame)
        self.assertEqual(callbacks, [(eventpoint, True)])
        track.stop()

    def test_single_chunk_fragment_marks_start_and_end_without_text_metadata(self):
        from src.tts.base import State
        from src.tts.engines.edge import _EdgePCMEmitter

        captured = []
        parent = SimpleNamespace(
            put_audio_frame=lambda samples, eventpoint: captured.append(
                (samples, eventpoint)
            )
        )
        owner = SimpleNamespace(
            state=State.RUNNING,
            sample_rate=16000,
            chunk=320,
            parent=parent,
        )
        emitter = _EdgePCMEmitter(
            owner,
            "private reply",
            {"turn_id": "turn-1", "generation": 0, "fragment_sequence": 0},
        )

        emitter._emit(np.ones(320, dtype=np.float32), final=True)

        eventpoint = captured[0][1]
        self.assertTrue(eventpoint["fragment_start"])
        self.assertTrue(eventpoint["fragment_end"])
        self.assertNotIn("text", eventpoint)


class PrivacyLoggingTests(unittest.TestCase):
    def test_media_log_only_records_fragment_boundaries(self):
        from src.avatars.base import BaseAvatar

        middle = {
            "turn_id": "turn-1",
            "generation": 0,
            "fragment_sequence": 0,
            "media_sequence": 10,
        }
        with patch("src.avatars.base.logger") as media_logger:
            BaseAvatar.notify(SimpleNamespace(), middle)
            BaseAvatar.notify(
                SimpleNamespace(),
                {**middle, "media_sequence": 0, "fragment_start": True},
            )
            BaseAvatar.notify(
                SimpleNamespace(),
                {**middle, "media_sequence": 20, "fragment_end": True},
            )

        self.assertEqual(media_logger.info.call_count, 2)

    def test_turn_aware_llm_and_media_logs_exclude_content(self):
        from src.config.schema import Config
        from src.llm.base import BaseLLM
        from src.avatars.base import BaseAvatar

        class FakeLLM(BaseLLM):
            def chat_stream(self, message, system_prompt=None):
                del message, system_prompt
                yield "private assistant reply。"

        avatar = SimpleNamespace(put_msg_txt=Mock())
        with patch("src.llm.base.logger") as llm_logger:
            FakeLLM(Config()).generate_response(
                "private transcript",
                avatar,
                datainfo={"turn_id": "turn-1", "generation": 0},
            )
        with patch("src.avatars.base.logger") as media_logger:
            BaseAvatar.notify(
                SimpleNamespace(),
                {
                    "text": "private assistant reply",
                    "turn_id": "turn-1",
                    "generation": 0,
                    "fragment_sequence": 0,
                },
            )

        logs = f"{llm_logger.method_calls} {media_logger.method_calls}"
        self.assertNotIn("private transcript", logs)
        self.assertNotIn("private assistant reply", logs)

    def test_asr_success_log_excludes_transcript(self):
        from src.asr.base import BaseASR

        class FakeASR(BaseASR):
            def _load_model(self):
                return None

            def _transcribe(self, _path):
                return {"text": "private transcript", "language": "zh"}

        engine = FakeASR.__new__(FakeASR)
        engine.model = object()
        engine.ensure_ready = Mock()
        engine._save_temp_audio = Mock(return_value="/tmp/fake-asr.wav")
        with (
            patch("src.asr.base.logger") as asr_logger,
            patch("src.asr.base.os.path.exists", return_value=False),
        ):
            result = engine.transcribe(b"private raw audio")

        self.assertEqual(result["text"], "private transcript")
        self.assertNotIn("private transcript", str(asr_logger.method_calls))
        self.assertNotIn("private raw audio", str(asr_logger.method_calls))


if __name__ == "__main__":
    unittest.main()
