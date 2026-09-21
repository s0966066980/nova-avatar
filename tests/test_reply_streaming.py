# Copyright (c) 2026 Kedreamix
# Modified by HongXian0903, 2026
# SPDX-License-Identifier: Apache-2.0

import unittest
import asyncio
import json
import subprocess
import sys
import os
import time
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch
from pathlib import Path

import yaml

from src.config.schema import Config
from src.config.loader import dict_to_config
from src.server.reply_streaming.metrics import TurnMetrics
from src.server.reply_streaming.media_debt import MediaDebtBudget
from src.server.reply_streaming.turn import TurnContext, TurnState
from src.llm.base import BaseLLM
from src.llm.engines.openai import OpenAILLM
from src.server.reply_streaming.fragmenter import SemanticFragmenter
from src.server.reply_streaming.channel import (
    BackpressureTruncated,
    BoundedFragmentChannel,
    PlayableFragment,
)
from src.server.reply_streaming.producer import ProducerResult, ReplyFragmentProducer
from src.server.reply_streaming.soak import build_soak_report


FIRST_SENTENCE = "這是一段足夠長度的第一句話用來觸發分段語音合成開始。"
SECOND_SENTENCE = "這是接在後面的第二句，用來模擬模型還在繼續生成內容。"
TOKEN_GAP_SECONDS = 0.12


class RecordingAvatar:
    def __init__(self):
        self.events = []

    def put_msg_txt(self, text, datainfo=None):
        self.events.append(
            {
                "at": time.perf_counter(),
                "text": text,
                "datainfo": dict(datainfo or {}),
            }
        )


class SlowSentenceLLM(BaseLLM):
    def chat_stream(self, message, system_prompt=None, **kwargs):
        yield FIRST_SENTENCE
        time.sleep(TOKEN_GAP_SECONDS)
        yield SECOND_SENTENCE


class StreamingVersusOneShotTtsTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(llm=SimpleNamespace(system_prompt="測試"))

    def test_streaming_starts_tts_and_avatar_before_legacy_one_shot(self):
        streaming_avatar = RecordingAvatar()
        oneshot_avatar = RecordingAvatar()

        streaming_started = time.perf_counter()
        SlowSentenceLLM(self.config).generate_response(
            "請回答",
            streaming_avatar,
            stream_to_avatar=True,
        )
        streaming_first = streaming_avatar.events[0]["at"] - streaming_started

        oneshot_started = time.perf_counter()
        full_text = SlowSentenceLLM(self.config).generate_response(
            "請回答",
            oneshot_avatar,
            stream_to_avatar=False,
        )
        oneshot_avatar.put_msg_txt(full_text)
        oneshot_first = oneshot_avatar.events[0]["at"] - oneshot_started

        self.assertGreaterEqual(len(streaming_avatar.events), 2)
        self.assertEqual(len(oneshot_avatar.events), 1)
        self.assertEqual(oneshot_avatar.events[0]["text"], FIRST_SENTENCE + SECOND_SENTENCE)
        self.assertLess(streaming_first, TOKEN_GAP_SECONDS / 2)
        self.assertGreater(oneshot_first, TOKEN_GAP_SECONDS * 0.8)
        self.assertLess(streaming_first, oneshot_first)
        self.assertIn(FIRST_SENTENCE.strip("。"), streaming_avatar.events[0]["text"])


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class ReplyStreamingConfigTests(unittest.TestCase):
    def test_reply_streaming_is_disabled_by_default(self):
        config = Config()

        self.assertFalse(config.reply_streaming.enabled)
        self.assertFalse(config.reply_streaming.decoupled_audio_clock)

    def test_reply_streaming_can_be_enabled_from_config_dict(self):
        config = dict_to_config({"reply_streaming": {"enabled": True}})

        self.assertTrue(config.reply_streaming.enabled)
        self.assertFalse(config.reply_streaming.decoupled_audio_clock)

    def test_decoupled_audio_clock_requires_an_explicit_opt_in(self):
        config = dict_to_config(
            {
                "reply_streaming": {
                    "enabled": True,
                    "decoupled_audio_clock": True,
                }
            }
        )

        self.assertTrue(config.reply_streaming.decoupled_audio_clock)

    def test_main_yaml_explicitly_keeps_reply_streaming_disabled(self):
        config_path = Path(__file__).resolve().parents[1] / "config" / "config.yaml"
        config_dict = yaml.safe_load(config_path.read_text(encoding="utf-8"))

        self.assertEqual(
            config_dict["reply_streaming"],
            {"enabled": False, "semantic_wait_seconds": 0.5},
        )

    def test_process_scoped_environment_can_enable_soak_without_changing_yaml(self):
        from src.config.loader import load_config

        config_path = Path(__file__).resolve().parents[1] / "config" / "config.yaml"
        with patch.dict(os.environ, {"NOVA_AVATAR_REPLY_STREAMING_ENABLED": "1"}):
            config = load_config(str(config_path))

        self.assertTrue(config.reply_streaming.enabled)


class SoakHarnessEventBrokerTests(unittest.IsolatedAsyncioTestCase):
    async def test_wait_for_preserves_unmatched_events_for_later_waiters(self):
        from scripts.run_voice_soak import EventBroker

        broker = EventBroker()
        broker.receive(json.dumps({"type": "state", "state": "llm"}))
        broker.receive(json.dumps({"type": "user_transcript", "turn_id": "turn-1"}))

        transcript = await broker.wait_for(
            lambda event: event.get("type") == "user_transcript",
            timeout=0.1,
        )
        state = await broker.wait_for(
            lambda event: event.get("type") == "state",
            timeout=0.1,
        )

        self.assertEqual(transcript["turn_id"], "turn-1")
        self.assertEqual(state["state"], "llm")


class TurnMetricsTests(unittest.TestCase):
    def test_snapshot_reports_only_structured_turn_measurements(self):
        clock = FakeClock()
        metrics = TurnMetrics("anonymous-turn", clock=clock)

        metrics.mark_speech_end()
        metrics.observe_media_debt(0.5)
        metrics.observe_media_debt(1.6)
        clock.advance(0.8)
        metrics.mark_first_audio()
        metrics.observe_av_offset(-0.04)
        metrics.observe_av_offset(0.07)
        clock.advance(1.0)
        metrics.mark_interrupt()
        clock.advance(0.15)
        metrics.mark_output_stopped()
        clock.advance(0.25)
        metrics.mark_listening_resumed()
        metrics.record_stale_drop("audio", "cancelled")
        metrics.observe_audio_pacing(
            lag_seconds=0.09,
            rebase_count=1,
            min_release_interval_seconds=0.02,
            catch_up_burst_count=0,
        )
        metrics.observe_tts_onset_preroll_ms(80.0)
        metrics.observe_tts_retry(after_commit=False)
        metrics.mark_stage_start("llm_first_token")
        clock.advance(0.05)
        metrics.mark_stage_end("llm_first_token")

        self.assertEqual(
            metrics.snapshot(),
            {
                "turn_id": "anonymous-turn",
                "first_audio_seconds": 0.8,
                "interrupt_stop_seconds": 0.15,
                "listening_resume_seconds": 0.4,
                "max_media_debt_seconds": 1.6,
                "max_abs_av_offset_seconds": 0.07,
                "stale_drops": {"audio:cancelled": 1},
                "audio_pacing_lag_ms": 90.0,
                "audio_pacing_rebase_count": 1,
                "audio_release_interval_ms": 20.0,
                "audio_catch_up_burst_count": 0,
                "tts_onset_preroll_ms": 80.0,
                "tts_retry_after_pcm_count": 1,
                "tts_retry_after_playback_commit_count": 0,
                "stage_seconds": {
                    "vad_endpoint": None,
                    "asr": None,
                    "llm_first_token": 0.05,
                    "llm_total": None,
                    "first_fragment": None,
                    "tts_first_encoded": None,
                    "tts_first_pcm": None,
                    "musetalk_first_batch": None,
                    "musetalk_inference_first_result": None,
                    "avatar_pasteback_done": None,
                    "webrtc_audio_enqueue": None,
                    "webrtc_video_enqueue": None,
                    "avatar_to_webrtc_commit": None,
                    "webrtc_audio_commit": None,
                },
            },
        )

    def test_stage_markers_are_fixed_and_idempotent(self):
        clock = FakeClock()
        metrics = TurnMetrics("anonymous-turn", clock=clock)

        metrics.mark_stage_start("asr")
        clock.advance(0.1)
        metrics.mark_stage_end("asr")
        clock.advance(0.1)
        metrics.mark_stage_start("asr")
        metrics.mark_stage_end("asr")
        clock.advance(0.2)

        self.assertEqual(metrics.snapshot()["stage_seconds"]["asr"], 0.1)
        with self.assertRaises(ValueError):
            metrics.mark_stage_start("transcript")

    def test_output_stop_is_ignored_until_interrupt_begins(self):
        clock = FakeClock()
        metrics = TurnMetrics("anonymous-turn", clock=clock)

        metrics.mark_output_stopped()
        clock.advance(1.0)
        metrics.mark_interrupt()
        clock.advance(0.1)
        metrics.mark_output_stopped()

        self.assertEqual(metrics.snapshot()["interrupt_stop_seconds"], 0.1)

    def test_snapshot_exposes_pacing_aggregates_without_content_fields(self):
        metrics = TurnMetrics("anonymous-turn")
        snapshot = metrics.snapshot()
        self.assertEqual(snapshot["audio_catch_up_burst_count"], 0)
        self.assertEqual(snapshot["tts_retry_after_playback_commit_count"], 0)
        self.assertTrue(
            {"text", "transcript", "pcm", "samples", "content"}.isdisjoint(snapshot)
        )


class MediaDebtBudgetTests(unittest.TestCase):
    def test_estimates_are_replaced_by_audio_and_hysteresis_requires_low_watermark(self):
        budget = MediaDebtBudget(high_watermark_seconds=2.0, low_watermark_seconds=1.0)

        budget.reserve("fragment-1", estimated_seconds=1.2)
        budget.reserve("fragment-2", estimated_seconds=1.0)
        self.assertEqual(budget.seconds, 2.2)
        self.assertTrue(budget.backpressured)

        budget.resolve("fragment-1", actual_seconds=0.8)
        budget.consume(0.3)
        self.assertEqual(budget.seconds, 1.5)
        self.assertTrue(budget.backpressured)

        budget.consume(0.5)
        self.assertEqual(budget.seconds, 1.0)
        self.assertFalse(budget.backpressured)

    def test_three_seconds_at_high_watermark_requests_boundary_truncation(self):
        clock = FakeClock()
        budget = MediaDebtBudget(
            high_watermark_seconds=2.0,
            low_watermark_seconds=1.0,
            backpressure_timeout_seconds=3.0,
            clock=clock,
        )

        budget.reserve("fragment-1", estimated_seconds=2.0)
        clock.advance(2.99)
        self.assertFalse(budget.truncation_requested)
        clock.advance(0.01)
        self.assertTrue(budget.truncation_requested)

        budget.consume(1.0)
        self.assertFalse(budget.backpressured)
        self.assertFalse(budget.truncation_requested)


class BoundedFragmentChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_producer_blocks_until_media_debt_reaches_low_watermark(self):
        channel = BoundedFragmentChannel()
        turn = TurnContext(turn_id="turn-1", generation=1)

        def fragment(sequence, seconds):
            return PlayableFragment(
                envelope=turn.envelope(stage="tts_fragment", sequence=sequence),
                text=f"fragment-{sequence}",
                estimated_seconds=seconds,
            )

        await channel.put(fragment(1, 1.2))
        await channel.put(fragment(2, 1.0))
        blocked_put = asyncio.create_task(channel.put(fragment(3, 0.5)))
        await asyncio.sleep(0)
        self.assertFalse(blocked_put.done())

        await channel.resolve("turn-1:1", actual_seconds=0.8)
        await channel.consume(0.3)
        self.assertFalse(blocked_put.done())
        await channel.consume(0.5)
        await asyncio.wait_for(blocked_put, timeout=0.1)

        self.assertEqual(
            [(await channel.get()).text for _ in range(3)],
            ["fragment-1", "fragment-2", "fragment-3"],
        )

    async def test_producer_truncates_only_when_next_fragment_reaches_channel(self):
        clock = FakeClock()
        budget = MediaDebtBudget(clock=clock)
        channel = BoundedFragmentChannel(budget)
        turn = TurnContext(turn_id="turn-1", generation=1)
        first = PlayableFragment(
            envelope=turn.envelope(stage="tts_fragment", sequence=1),
            text="first",
            estimated_seconds=2.0,
        )
        next_fragment = PlayableFragment(
            envelope=turn.envelope(stage="tts_fragment", sequence=2),
            text="next boundary",
            estimated_seconds=0.5,
        )

        await channel.put(first)
        clock.advance(3.0)

        with self.assertRaises(BackpressureTruncated):
            await asyncio.wait_for(channel.put(next_fragment), timeout=0.1)
        self.assertEqual(channel.qsize, 1)


class ReplyFragmentProducerTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_turn_stops_before_later_tokens_enter_channel(self):
        turn = TurnContext(turn_id="turn-1", generation=1)
        turn.transition(TurnState.LLM_STREAMING)
        channel = BoundedFragmentChannel()
        producer = ReplyFragmentProducer(
            turn,
            channel,
            estimate_seconds=lambda _text: 0.2,
        )

        async def tokens():
            yield "第一句。"
            turn.cancel("interrupt")
            yield "第二句。"

        result = await producer.run(tokens())

        self.assertEqual(result, ProducerResult.CANCELLED)
        self.assertEqual(channel.qsize, 1)
        self.assertEqual((await channel.get()).text, "第一句。")


class BaselineReplayHarnessTests(unittest.TestCase):
    def test_fake_replay_is_reproducible_content_free_and_judges_slos(self):
        project_root = Path(__file__).resolve().parents[1]
        command = [sys.executable, "scripts/replay_voice_baseline.py"]

        first = subprocess.check_output(command, cwd=project_root, text=True)
        second = subprocess.check_output(command, cwd=project_root, text=True)
        report = json.loads(first)

        self.assertEqual(first, second)
        self.assertEqual(report["mode"], "deterministic_fake_legacy")
        self.assertEqual(report["turns"], 5)
        self.assertTrue(report["slo_pass"])
        self.assertNotIn("你好", first)
        self.assertNotIn("assistant", first)

    def test_real_soak_report_is_content_free_and_applies_all_slos(self):
        metrics = []
        for index in range(50):
            metrics.append(
                {
                    "turn_id": f"turn-{index}",
                    "first_audio_seconds": 1.0,
                    "interrupt_stop_seconds": 0.18 if index % 10 == 0 else None,
                    "listening_resume_seconds": 0.45 if index % 10 == 0 else None,
                "max_media_debt_seconds": 1.8,
                "max_abs_av_offset_seconds": 0.07,
                "stale_drops": {},
                "stage_seconds": {
                    "llm_first_token": 0.08,
                    "tts_first_pcm": 0.4,
                },
            }
            )

        report = build_soak_report(
            metrics,
            scenario_counts={"normal": 45, "interrupt": 5},
            stale_events=0,
            environment={"gpu": "RTX 4090", "llm": "llama.cpp"},
        )

        self.assertTrue(report["slo_pass"])
        self.assertEqual(report["turns"], 50)
        self.assertEqual(report["metrics"]["stage_seconds"]["tts_first_pcm"]["p95"], 0.4)
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("transcript", serialized)
        self.assertNotIn("assistant_text", serialized)


class TurnContextTests(unittest.TestCase):
    def test_terminal_turn_rejects_stale_envelopes_and_cannot_move_forward(self):
        turn = TurnContext(turn_id="turn-1", generation=3)
        envelope = turn.envelope(stage="llm_token", sequence=1)

        turn.transition(TurnState.LLM_STREAMING)
        self.assertTrue(turn.accepts(envelope))

        turn.cancel("interrupt")
        turn.cancel("disconnect")
        self.assertTrue(turn.cancelled.is_set())
        self.assertEqual(turn.state, TurnState.CANCELLED)
        self.assertEqual(turn.terminal_reason, "interrupt")
        self.assertFalse(turn.accepts(envelope))
        self.assertFalse(
            TurnContext(turn_id="turn-1", generation=4).accepts(envelope)
        )
        with self.assertRaises(RuntimeError):
            turn.transition(TurnState.SYNTHESIZING)

    def test_normal_turn_completes_only_after_draining(self):
        turn = TurnContext(turn_id="turn-1", generation=1)

        for state in (
            TurnState.LLM_STREAMING,
            TurnState.SYNTHESIZING,
            TurnState.SPEAKING,
            TurnState.DRAINING,
        ):
            turn.transition(state)
        turn.complete("played")

        self.assertEqual(turn.state, TurnState.COMPLETED)
        self.assertEqual(turn.terminal_reason, "played")
        self.assertFalse(turn.cancelled.is_set())


class LLMGenerationFenceTests(unittest.TestCase):
    def test_turn_aware_streaming_emits_short_strong_sentence_immediately(self):
        class FakeLLM(BaseLLM):
            def chat_stream(self, message, system_prompt=None):
                del message, system_prompt
                yield "好的。"
                yield "稍後補充。"

        class FakeAvatar:
            def __init__(self):
                self.fragments = []
                self.deltas = []

            def put_msg_txt(self, text, data):
                self.fragments.append((text, data))

            def notify_llm_chunk(self, text, data):
                self.deltas.append((text, data))

        avatar = FakeAvatar()
        response = FakeLLM(Config()).generate_response(
            "fixture",
            avatar,
            datainfo={"turn_id": "turn-1", "generation": 1},
        )

        self.assertEqual(response, "好的。稍後補充。")
        self.assertEqual([item[0] for item in avatar.fragments], ["好的。", "稍後補充。"])
        self.assertEqual([item[0] for item in avatar.deltas], ["好的。", "稍後補充。"])
        self.assertEqual([item[1]["llm_sequence"] for item in avatar.deltas], [0, 1])

    def test_rejected_token_never_reaches_text_processor_or_avatar(self):
        class FakeLLM(BaseLLM):
            def chat_stream(self, message, system_prompt=None):
                del message, system_prompt
                yield "這是第一個仍然有效而且長度足夠送出的語音回覆片段。"
                yield "這是舊輪次不應該送出的第二個語音回覆片段。"

        class FakeAvatar:
            def __init__(self):
                self.fragments = []

            def put_msg_txt(self, text, data):
                self.fragments.append((text, data))

        llm = FakeLLM(Config())
        avatar = FakeAvatar()

        response = llm.generate_response(
            "fixture",
            avatar,
            datainfo={"turn_id": "turn-1", "generation": 5},
            chunk_guard=lambda sequence: sequence == 0,
        )

        self.assertEqual(
            response,
            "這是第一個仍然有效而且長度足夠送出的語音回覆片段。",
        )
        self.assertEqual(
            avatar.fragments,
            [
                (
                    response,
                    {
                        "turn_id": "turn-1",
                        "generation": 5,
                        "fragment_sequence": 0,
                    },
                )
            ],
        )


class LLMHistoryTransactionTests(unittest.TestCase):
    def test_deferred_voice_history_commits_only_played_text_by_turn_id(self):
        llm = OpenAILLM(config=Config(), api_key="fixture")
        completion = [
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="generated reply"))]
            )
        ]
        llm._client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=Mock(return_value=completion))
            )
        )

        response = llm.generate_response(
            "user fixture",
            stream_to_avatar=False,
            datainfo={"turn_id": "voice-turn"},
            defer_history_commit=True,
        )

        self.assertEqual(response, "generated reply")
        self.assertEqual(llm.conversation_history, [])
        self.assertTrue(
            llm.commit_pending_history_turn(
                "voice-turn",
                assistant_text="played only",
                terminal_reason="interrupted",
            )
        )
        self.assertEqual(
            llm.conversation_history,
            [
                {"role": "user", "content": "user fixture"},
                {"role": "assistant", "content": "played only"},
            ],
        )
        self.assertFalse(
            llm.commit_pending_history_turn(
                "voice-turn",
                assistant_text="duplicate",
                terminal_reason="interrupted",
            )
        )

    def test_generator_does_not_commit_unplayed_text(self):
        llm = OpenAILLM(config=Config(), api_key="fixture")
        completion = [
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="已產生但尚未播放"))]
            )
        ]
        create = Mock(return_value=completion)
        llm._client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        transaction = llm.begin_history_turn("user fixture", turn_id="turn-1")

        generated = "".join(
            llm.chat_stream(
                "user fixture",
                history_transaction=transaction,
            )
        )

        self.assertEqual(generated, "已產生但尚未播放")
        self.assertEqual(llm.conversation_history, [])
        llm.commit_history_turn(
            transaction,
            assistant_text="已播放",
            terminal_reason="interrupted",
        )
        self.assertEqual(
            llm.conversation_history,
            [
                {"role": "user", "content": "user fixture"},
                {"role": "assistant", "content": "已播放"},
            ],
        )

    def test_llm_error_commits_user_but_not_partial_generated_text(self):
        class BrokenCompletion:
            def __iter__(self):
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="partial"))]
                )
                raise RuntimeError("fixture failure")

        llm = OpenAILLM(config=Config(), api_key="fixture")
        llm._client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=Mock(return_value=BrokenCompletion()))
            )
        )

        with self.assertRaisesRegex(RuntimeError, "fixture failure"):
            llm.generate_response(
                "user fixture",
                stream_to_avatar=False,
                datainfo={"turn_id": "failed-turn"},
            )

        self.assertEqual(
            llm.conversation_history,
            [{"role": "user", "content": "user fixture"}],
        )

    def test_legacy_generate_response_commits_after_stream_completes(self):
        llm = OpenAILLM(config=Config(), api_key="fixture")
        completion = [
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="full reply"))]
            )
        ]
        llm._client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=Mock(return_value=completion))
            )
        )

        response = llm.generate_response(
            "user fixture",
            stream_to_avatar=False,
            datainfo={"turn_id": "legacy-turn"},
        )

        self.assertEqual(response, "full reply")
        self.assertEqual(
            llm.conversation_history,
            [
                {"role": "user", "content": "user fixture"},
                {"role": "assistant", "content": "full reply"},
            ],
        )


class SemanticFragmenterTests(unittest.TestCase):
    def test_strong_minimum_joins_short_sentences_before_tts(self):
        fragmenter = SemanticFragmenter(
            soft_limit_chars=72,
            hard_limit_chars=120,
            strong_min_chars=72,
        )

        text = "甲" * 40 + "。" + "乙" * 40 + "。"
        self.assertEqual(fragmenter.feed(text), [text])

    def test_strong_and_weak_punctuation_follow_exact_thresholds_across_tokens(self):
        fragmenter = SemanticFragmenter()

        self.assertEqual(fragmenter.feed("好"), [])
        self.assertEqual(fragmenter.feed("。"), ["好。"])
        self.assertEqual(fragmenter.feed("一二三四五六七八九十甲，"), [])
        self.assertEqual(fragmenter.feed("乙，"), [])
        self.assertEqual(fragmenter.feed("完成。"), ["一二三四五六七八九十甲，乙，完成。"])

    def test_weak_punctuation_does_not_split_a_natural_sentence(self):
        text = "串流模式需要保留完整語意，否則語音會在不自然的位置停頓，而且下一段的語氣也會重新起頭。"
        fragmenter = SemanticFragmenter()

        self.assertEqual(fragmenter.feed(text), [text])

    def test_commas_do_not_cut_a_sentence_while_tokens_are_still_arriving(self):
        fragmenter = SemanticFragmenter()
        clause = "一二三四五六七八九十" * 4
        incoming = clause + "，後半句也還沒結束"
        actual = []
        for character in incoming:
            actual.extend(fragmenter.feed(character))

        self.assertEqual(actual, [])
        self.assertEqual(fragmenter.feed("。"), [incoming + "。"])

    def test_sentence_closing_marks_stay_with_the_fragment(self):
        fragmenter = SemanticFragmenter()

        self.assertEqual(
            fragmenter.feed("他回答：「今天會完成。」接著繼續說明。"),
            ["他回答：「今天會完成。」", "接著繼續說明。"],
        )

    def test_sentence_closing_mark_can_arrive_in_a_later_token(self):
        fragmenter = SemanticFragmenter()

        self.assertEqual(fragmenter.feed("他回答：「今天會完成。"), [])
        self.assertEqual(
            fragmenter.feed("」接著繼續說明。"),
            ["他回答：「今天會完成。」", "接著繼續說明。"],
        )

    def test_inline_punctuation_stays_inside_url_and_version(self):
        fragmenter = SemanticFragmenter()

        self.assertEqual(
            fragmenter.feed("版本是 v1.2.3，請開啟 example.com 查看說明。"),
            ["版本是 v1.2.3，請開啟 example.com 查看說明。"],
        )
        fragmenter = SemanticFragmenter()
        self.assertEqual(
            fragmenter.feed("請查看 https://example.com/path。"),
            ["請查看 https://example.com/path。"],
        )

    def test_unpunctuated_text_waits_for_stream_end_without_hard_cutting(self):
        chinese = "一二三四五六七八九十" * 13
        fragmenter = SemanticFragmenter()

        self.assertEqual(fragmenter.feed(chinese), [])
        self.assertEqual(fragmenter.flush(), [chinese])

    def test_wait_expiry_releases_an_existing_clause_within_latency_budget(self):
        now = [0.0]
        fragmenter = SemanticFragmenter(
            weak_min_chars=1,
            semantic_wait_seconds=0.5,
            clock=lambda: now[0],
        )
        self.assertEqual(fragmenter.feed("這段話尚未結束，"), [])
        now[0] = 0.49
        self.assertEqual(fragmenter.feed("接著"), [])
        now[0] = 0.5
        self.assertEqual(
            fragmenter.feed("補充"),
            ["這段話尚未結束，"],
        )

    def test_number_sequences_and_decimal_points_stay_intact(self):
        fragmenter = SemanticFragmenter(soft_limit_chars=24, hard_limit_chars=32)
        number = "12345678901234567890123456789012"

        fragments = fragmenter.feed(f"版本號碼 {number} 還有後續")

        self.assertEqual(fragments, [])
        self.assertEqual(fragmenter.flush(), [f"版本號碼 {number} 還有後續"])
        self.assertEqual(SemanticFragmenter().feed("價格是 3.14 元。"), ["價格是 3.14 元。"])

    def test_fragmentation_is_independent_of_llm_token_boundaries(self):
        text = "alpha bravo charlie delta echo foxtrot golf 完成。"
        whole = SemanticFragmenter()
        expected = whole.feed(text) + whole.flush()
        incremental = SemanticFragmenter()
        actual = []
        for character in text:
            actual.extend(incremental.feed(character))
        actual.extend(incremental.flush())

        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
