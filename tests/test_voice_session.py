import asyncio
import json
import time
import unittest
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import numpy as np

from src.server.voice_session import (
    OUTPUT_STALL_FRAMES,
    VoiceTurnSession,
    speech_input_rejection_reason,
)


class FakeAvatar:
    def __init__(self):
        self.messages = []
        self.flush_count = 0
        self.media_guard = None
        self.on_stale_drop = None
        self.on_fragment_queued = None

    def put_msg_txt(self, text, data=None):
        eventpoint = data or {}
        self.messages.append((text, eventpoint))
        if self.on_fragment_queued is not None:
            self.on_fragment_queued(text, eventpoint)

    def flush_talk(self):
        self.flush_count += 1

    def configure_media_fence(
        self,
        *,
        media_guard,
        on_stale_drop,
        on_fragment_queued=None,
        **_unused,
    ):
        self.media_guard = media_guard
        self.on_stale_drop = on_stale_drop
        self.on_fragment_queued = on_fragment_queued


class FakeSegmenter:
    def __init__(self, segment=None):
        self.segment = segment
        self.is_speaking = False
        self.reset_count = 0

    def process(self, _pcm):
        if self.segment is None:
            return []
        segment, self.segment = self.segment, None
        return [segment]

    def flush(self):
        return []

    def reset(self):
        self.reset_count += 1
        self.is_speaking = False


class FakeASR:
    def transcribe(self, _audio):
        return {"text": "你好", "language": "zh"}


class VoiceTurnSessionTests(unittest.IsolatedAsyncioTestCase):
    def test_speech_input_quality_rejects_short_audio_and_low_confidence_text(self):
        settings = SimpleNamespace(
            min_speech_ms=450,
            min_audio_rms=0.003,
            min_confidence=0.35,
        )
        audio = np.ones(16000, dtype=np.int16) * 600

        self.assertEqual(
            speech_input_rejection_reason(
                audio, 16000, 200, {"text": "上一輪內容"}, settings
            ),
            "speech_too_short",
        )
        self.assertEqual(
            speech_input_rejection_reason(
                audio, 16000, 700, {"text": "上一輪內容", "confidence": 0.1}, settings
            ),
            "transcript_low_confidence",
        )
        self.assertIsNone(
            speech_input_rejection_reason(
                audio, 16000, 700, {"text": "有效問題", "confidence": 0.9}, settings
            )
        )

    async def test_low_confidence_speech_transcript_never_reaches_llm(self):
        segment = SimpleNamespace(
            audio=np.ones(16000, dtype=np.int16) * 600,
            sample_rate=16000,
            speech_ms=700,
        )
        session, _, events = self.make_session(segment, clock=lambda: 0.0)
        session.config.asr = SimpleNamespace(
            min_speech_ms=450,
            min_audio_rms=0.003,
            min_confidence=0.35,
        )
        session._asr = SimpleNamespace(
            transcribe=Mock(return_value={"text": "上一輪內容", "confidence": 0.1})
        )

        with patch("src.server.voice_session.llm_response", return_value="") as llm:
            await session.feed_pcm(np.ones(512, dtype=np.int16))
            await session._turn_task

            llm.assert_not_called()
            self.assertNotIn("user_transcript", [event["type"] for event in events])
            self.assertIsNone(session._turn_task)
            self.assertIsNone(session._turn_id)
            self.assertTrue(session._gate_open)
            self.assertEqual(events[-1]["state"], "listening")

            session._segmenter.segment = segment
            session._asr.transcribe = Mock(
                return_value={"text": "下一輪有效問題", "confidence": 0.9}
            )
            await session.feed_pcm(np.ones(512, dtype=np.int16))
            await session._turn_task

        llm.assert_called_once()
        self.assertIn("下一輪有效問題", str(llm.call_args))
        self.assertTrue(session._gate_open)
        await session.close()

    async def test_short_non_speech_reopens_listening_without_running_asr(self):
        segment = SimpleNamespace(
            audio=np.ones(16000, dtype=np.int16) * 600,
            sample_rate=16000,
            speech_ms=200,
        )
        session, _, events = self.make_session(segment)
        session.config.asr = SimpleNamespace(
            min_speech_ms=450,
            min_audio_rms=0.003,
            min_confidence=0.35,
        )
        session._asr = SimpleNamespace(transcribe=Mock())

        await session.feed_pcm(np.ones(512, dtype=np.int16))
        await session._turn_task

        session._asr.transcribe.assert_not_called()
        self.assertIsNone(session._turn_task)
        self.assertIsNone(session._turn_id)
        self.assertTrue(session._gate_open)
        self.assertEqual(events[-1]["state"], "listening")
        await session.close()

    def make_session(self, segment=None, *, clock=time.monotonic, streaming=True):
        config = SimpleNamespace(
            asr=SimpleNamespace(type="whisper", model_size="base", language="zh"),
            vad=SimpleNamespace(),
            reply_streaming=SimpleNamespace(enabled=streaming),
        )
        avatar = FakeAvatar()
        session = VoiceTurnSession(7, config, avatar, clock=clock)
        session._segmenter = FakeSegmenter(segment)
        session._asr = FakeASR()
        events = []
        session.attach_event_sink(lambda raw: events.append(json.loads(raw)))
        return session, avatar, events

    async def test_final_transcript_and_response_share_one_turn(self):
        segment = SimpleNamespace(
            audio=np.ones(1600, dtype=np.int16),
            sample_rate=16000,
        )
        session, avatar, events = self.make_session(segment)

        # 逐句串流後，推送 TTS 的責任在 llm_response 內部，輪次只負責把
        # turn_id 交下去。用 side_effect 模擬它逐句回推。
        def fake_llm(
            text,
            avatar_stream,
            *,
            stream_to_avatar=True,
            datainfo=None,
            chunk_guard=None,
            defer_history_commit=False,
        ):
            self.assertTrue(stream_to_avatar)
            self.assertTrue(chunk_guard(0))
            self.assertEqual(datainfo["generation"], session._generation)
            fragment_info = dict(datainfo or {})
            fragment_info.pop("on_board", None)
            fragment_info["fragment_sequence"] = 0
            avatar_stream.put_msg_txt("您好", fragment_info)
            return "您好"

        with patch("src.server.voice_session.llm_response", side_effect=fake_llm):
            await session.feed_pcm(np.ones(512, dtype=np.int16))
            task = session._turn_task
            self.assertIsNotNone(task)
            await task

        transcript = next(item for item in events if item["type"] == "user_transcript")
        eventpoint = avatar.messages[0][1]
        self.assertNotIn("assistant_fragment", [item["type"] for item in events])
        session.on_output_audio_frame(eventpoint, True)
        answer = next(item for item in events if item["type"] == "assistant_fragment")
        self.assertEqual(transcript["turn_id"], answer["turn_id"])
        self.assertEqual(
            avatar.messages,
            [
                (
                    "您好",
                    {
                        "turn_id": answer["turn_id"],
                        "generation": 0,
                        "fragment_sequence": 0,
                    },
                )
            ],
        )
        self.assertEqual([item["seq"] for item in events], sorted(item["seq"] for item in events))
        await session.close()


    async def test_legacy_turn_exposes_first_audio_metric(self):
        class FakeClock:
            now = 0.0

            def __call__(self):
                return self.now

        clock = FakeClock()
        segment = SimpleNamespace(
            audio=np.ones(1600, dtype=np.int16),
            sample_rate=16000,
        )
        session, _, _ = self.make_session(segment, clock=clock)

        with patch("src.server.voice_session.llm_response", return_value="您好"):
            await session.feed_pcm(np.ones(512, dtype=np.int16))
            await session._turn_task
        clock.now = 0.8
        session.on_output_audio(True)

        self.assertEqual(session.metrics_snapshot()["first_audio_seconds"], 0.8)
        await session.close()

    async def test_streaming_vad_does_not_block_the_media_event_loop(self):
        started = Event()
        release = Event()

        class SlowSegmenter(FakeSegmenter):
            def process(self, _pcm):
                started.set()
                release.wait(timeout=0.15)
                return []

        session, _, _ = self.make_session()
        session._segmenter = SlowSegmenter()

        started_at = time.monotonic()
        feed_task = asyncio.create_task(
            session.feed_pcm(np.ones(512, dtype=np.int16))
        )
        await asyncio.sleep(0)
        heartbeat_delay = time.monotonic() - started_at
        release.set()
        await feed_task

        self.assertTrue(started.is_set())
        self.assertLess(heartbeat_delay, 0.05)
        await session.close()

    async def test_microphone_resampling_does_not_block_the_media_event_loop(self):
        started = Event()
        release = Event()
        keep_track_open = asyncio.Event()

        class SlowResampler:
            def resample(self, _frame):
                started.set()
                release.wait(timeout=0.15)
                return []

        class OneFrameTrack:
            def __init__(self):
                self.calls = 0

            async def recv(self):
                self.calls += 1
                if self.calls == 1:
                    return object()
                await keep_track_open.wait()

        session, _, _ = self.make_session()
        session._resampler = SlowResampler()

        started_at = time.monotonic()
        session.start_track(OneFrameTrack())
        await asyncio.sleep(0)
        heartbeat_delay = time.monotonic() - started_at
        release.set()

        self.assertTrue(started.is_set())
        self.assertLess(heartbeat_delay, 0.05)
        await session.close()

    async def test_push_to_talk_finalize_does_not_block_the_media_event_loop(self):
        started = Event()
        release = Event()

        class SlowFlushSegmenter(FakeSegmenter):
            def flush(self):
                started.set()
                release.wait(timeout=0.15)
                return []

        session, _, _ = self.make_session()
        session._segmenter = SlowFlushSegmenter()

        started_at = time.monotonic()
        session.handle_control(
            json.dumps({"type": "capture", "enabled": False, "finalize": True})
        )
        control_delay = time.monotonic() - started_at
        await asyncio.sleep(0)
        heartbeat_delay = time.monotonic() - started_at
        release.set()

        self.assertLess(control_delay, 0.05)
        self.assertLess(heartbeat_delay, 0.05)
        await session.close()

    async def test_outbound_audio_closes_gate_and_emits_speaking_edges(self):
        session, _, events = self.make_session()
        self.assertTrue(session._gate_open)
        session.on_output_audio(True)
        self.assertFalse(session._gate_open)
        session.on_output_audio(False)
        session.on_output_audio(False)
        session.on_output_audio(False)
        kinds = [item["type"] for item in events]
        self.assertIn("speaking_start", kinds)
        self.assertIn("speaking_end", kinds)
        await session.close()

    async def test_interrupt_flushes_old_turn_and_reopens_after_guard(self):
        session, avatar, events = self.make_session()
        session._turn_id = "old-turn"

        class MediaPlayer:
            discard_count = 0

            def discard_stale_media(self):
                self.discard_count += 1

        media_player = MediaPlayer()
        session.attach_media_player(media_player)
        with patch("src.server.voice_session.asyncio.sleep", new=AsyncMock()):
            await session.interrupt()
        self.assertEqual(avatar.flush_count, 1)
        self.assertEqual(media_player.discard_count, 1)
        self.assertTrue(session._gate_open)
        self.assertTrue(any(item["type"] == "turn_cancelled" for item in events))
        await session.close()

    async def test_avatar_media_guard_rejects_cancelled_generation(self):
        session, avatar, _ = self.make_session()
        session._turn_id = "turn-1"
        session._start_turn_context("turn-1")
        eventpoint = {
            "turn_id": "turn-1",
            "generation": 0,
            "fragment_sequence": 0,
            "media_sequence": 0,
        }

        self.assertIsNotNone(avatar.media_guard)
        self.assertTrue(avatar.media_guard(eventpoint, "avatar_audio_enqueue"))
        session._turn_id = None
        self.assertFalse(avatar.media_guard(eventpoint, "avatar_audio_enqueue"))
        session._turn_id = "turn-1"
        with patch("src.server.voice_session.asyncio.sleep", new=AsyncMock()):
            await session.interrupt()
        self.assertFalse(avatar.media_guard(eventpoint, "avatar_audio_enqueue"))
        avatar.on_stale_drop("avatar_audio", "stale_generation")
        self.assertEqual(
            session.metrics_snapshot()["stale_drops"],
            {"avatar_audio:stale_generation": 1},
        )
        await session.close()

    async def test_executor_llm_cannot_enqueue_after_turn_is_cancelled(self):
        segment = SimpleNamespace(
            audio=np.ones(1600, dtype=np.int16),
            sample_rate=16000,
        )
        session, avatar, _ = self.make_session(segment)
        started = Event()
        release = Event()
        finished = Event()

        def blocked_llm(
            _text,
            avatar_stream,
            *,
            stream_to_avatar=True,
            datainfo=None,
            chunk_guard=None,
            defer_history_commit=False,
        ):
            started.set()
            release.wait(timeout=1)
            if chunk_guard is None or chunk_guard(0):
                avatar_stream.put_msg_txt("舊回覆", dict(datainfo or {}))
            finished.set()
            return "舊回覆"

        with patch("src.server.voice_session.llm_response", side_effect=blocked_llm):
            await session.feed_pcm(np.ones(512, dtype=np.int16))
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            with patch("src.server.voice_session.asyncio.sleep", new=AsyncMock()):
                await session.interrupt()
            release.set()
            self.assertTrue(await asyncio.to_thread(finished.wait, 1))

        self.assertEqual(avatar.messages, [])
        await session.close()

    async def test_disconnect_fences_executor_llm_output(self):
        segment = SimpleNamespace(
            audio=np.ones(1600, dtype=np.int16),
            sample_rate=16000,
        )
        session, avatar, _ = self.make_session(segment)
        started = Event()
        release = Event()
        finished = Event()

        def blocked_llm(
            _text,
            avatar_stream,
            *,
            stream_to_avatar=True,
            datainfo=None,
            chunk_guard=None,
            defer_history_commit=False,
        ):
            started.set()
            release.wait(timeout=1)
            if chunk_guard is None or chunk_guard(0):
                avatar_stream.put_msg_txt("舊回覆", dict(datainfo or {}))
            finished.set()
            return "舊回覆"

        with patch("src.server.voice_session.llm_response", side_effect=blocked_llm):
            await session.feed_pcm(np.ones(512, dtype=np.int16))
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            await session.close()
            release.set()
            self.assertTrue(await asyncio.to_thread(finished.wait, 1))

        self.assertEqual(avatar.messages, [])


class ReplyModeBehaviorTests(unittest.IsolatedAsyncioTestCase):
    def make_session(self, *, streaming):
        config = SimpleNamespace(
            asr=SimpleNamespace(type="whisper", model_size="base", language="zh"),
            vad=SimpleNamespace(),
            reply_streaming=SimpleNamespace(enabled=streaming),
        )
        avatar = FakeAvatar()
        session = VoiceTurnSession(7, config, avatar)
        events = []
        session.attach_event_sink(lambda raw: events.append(json.loads(raw)))
        session._segmenter = FakeSegmenter()
        session._asr = FakeASR()
        return session, avatar, events

    async def test_legacy_text_turn_emits_one_complete_response(self):
        session, avatar, events = self.make_session(streaming=False)
        calls = []

        def fake_llm(text, avatar_stream, **kwargs):
            calls.append((text, kwargs))
            return "完整回覆"

        with patch("src.server.voice_session.llm_response", side_effect=fake_llm):
            started = await session.start_text_turn("請回答", interrupt=False)
            await session._turn_task

        self.assertEqual(started["reply_mode"], "legacy")
        self.assertFalse(calls[0][1].get("stream_to_avatar", True))
        self.assertEqual(calls[0][1]["datainfo"]["turn_id"], started["turn_id"])
        self.assertTrue(callable(calls[0][1]["datainfo"]["on_board"]))
        self.assertEqual(calls[0][1].get("chunk_guard"), None)
        self.assertFalse(calls[0][1].get("defer_history_commit", False))
        responses = [item for item in events if item["type"] == "assistant_response"]
        self.assertEqual([item["text"] for item in responses], ["完整回覆"])
        self.assertEqual(len(avatar.messages), 1)
        text, eventpoint = avatar.messages[0]
        self.assertEqual(text, "完整回覆")
        self.assertEqual(eventpoint["turn_id"], started["turn_id"])
        self.assertEqual(eventpoint["generation"], 0)
        self.assertEqual(eventpoint["fragment_sequence"], 0)
        self.assertNotIn("assistant_fragment", [item["type"] for item in events])

        session.on_output_audio_frame(eventpoint, True)

        fragments = [item for item in events if item["type"] == "assistant_fragment"]
        self.assertEqual([item["text"] for item in fragments], ["完整回覆"])
        await session.close()

    async def test_text_turn_pauses_microphone_before_llm_or_avatar_output(self):
        session, _avatar, events = self.make_session(streaming=False)
        microphone_segment = SimpleNamespace(
            audio=np.ones(1600, dtype=np.int16),
            sample_rate=16000,
            speech_ms=700,
        )
        session._segmenter.segment = microphone_segment
        self.assertTrue(session._gate_open)

        with patch("src.server.voice_session.llm_response", return_value="簡短回答"):
            started = await session.start_text_turn("執行測試", interrupt=False)

            self.assertFalse(session._gate_open)
            await session.feed_pcm(np.ones(512, dtype=np.int16))
            self.assertIs(session._segmenter.segment, microphone_segment)
            self.assertEqual(session._turn_id, started["turn_id"])
            self.assertNotIn("speech_detected", [event.get("state") for event in events])
            await session._turn_task

        await session.close()

    async def test_board_events_include_a_stable_board_id(self):
        session, _avatar, events = self.make_session(streaming=False)

        def fake_llm(_text, _avatar_stream, **kwargs):
            info = kwargs["datainfo"]
            info["on_board"](
                {"kind": "begin", "title": "部署前檢查", "turn_id": info["turn_id"]}
            )
            info["on_board"](
                {
                    "kind": "item",
                    "index": 0,
                    "title": "確認設定",
                    "body": "確認環境變數已套用。",
                    "turn_id": info["turn_id"],
                }
            )
            return "先確認部署設定。"

        with patch("src.server.voice_session.llm_response", side_effect=fake_llm):
            started = await session.start_text_turn("列出部署步驟", interrupt=False)
            await session._turn_task
            await asyncio.sleep(0)

        board_events = [event for event in events if event["type"] in {"board_begin", "board_item"}]
        self.assertEqual([event["type"] for event in board_events], ["board_begin", "board_item"])
        self.assertTrue(all(event["board_id"] == started["turn_id"] for event in board_events))
        await session.close()

    async def test_display_receipt_is_forwarded_once_per_presenter_item(self):
        session, _avatar, _events = self.make_session(streaming=False)

        with patch(
            "src.server.voice_session.acknowledge_session_board_item",
            create=True,
            return_value=True,
        ) as acknowledge:
            receipt = json.dumps(
                {
                    "type": "board_displayed",
                    "turn_id": "turn-42",
                    "board_id": "turn-42",
                    "item_index": 1,
                    "presenter": "console",
                }
            )
            session.handle_control(receipt)
            session.handle_control(receipt)

        acknowledge.assert_called_once_with(
            session.sessionid,
            turn_id="turn-42",
            board_id="turn-42",
            item_index=1,
            presenter="console",
        )
        await session.close()

    async def test_legacy_no_first_audio_fails_and_releases_turn(self):
        session, avatar, events = self.make_session(streaming=False)

        with patch(
            "src.server.voice_session.llm_response",
            return_value="完整但沒有開始播放的回覆",
        ):
            await session.start_text_turn("測試舊模式無首音", interrupt=False)
            await session._turn_task

        for _ in range(OUTPUT_STALL_FRAMES):
            session.on_output_audio(False)

        errors = [
            item
            for item in events
            if item["type"] == "state" and item.get("state") == "error"
        ]
        self.assertEqual(errors[-1]["error"], "playback_error_before_commit")
        self.assertIsNone(session._turn_id)
        self.assertEqual(avatar.flush_count, 1)
        await session.close()

    async def test_streaming_text_turn_uses_guarded_played_fragment_delivery(self):
        session, avatar, events = self.make_session(streaming=True)

        def fake_llm(
            text,
            avatar_stream,
            *,
            stream_to_avatar=True,
            datainfo=None,
            chunk_guard=None,
            defer_history_commit=False,
        ):
            self.assertEqual(text, "請串流")
            self.assertTrue(stream_to_avatar)
            self.assertIsNotNone(datainfo)
            self.assertIsNotNone(chunk_guard)
            self.assertTrue(defer_history_commit)
            self.assertTrue(chunk_guard(0))
            info = dict(datainfo)
            info["fragment_sequence"] = 0
            avatar_stream.put_msg_txt("逐段回覆", info)
            return "逐段回覆"

        with patch("src.server.voice_session.llm_response", side_effect=fake_llm):
            started = await session.start_text_turn("請串流", interrupt=False)
            await session._turn_task

        self.assertEqual(started["reply_mode"], "streaming")
        self.assertEqual(
            [item for item in events if item["type"] == "assistant_fragment"],
            [],
        )
        session.on_output_audio_frame(avatar.messages[0][1], True)
        fragments = [item for item in events if item["type"] == "assistant_fragment"]
        self.assertEqual([item["text"] for item in fragments], ["逐段回覆"])
        await session.close()

    async def test_streaming_enqueues_tts_before_legacy_one_shot_finishes(self):
        first = "這是一段足夠長度的第一句話用來觸發分段語音合成開始。"
        second = "這是接在後面的第二句，用來模擬模型還在繼續生成內容。"
        gap = 0.08

        async def run_mode(streaming):
            session, avatar, _events = self.make_session(streaming=streaming)
            started_at = time.perf_counter()
            first_tts_at = []

            def fake_llm(text, avatar_stream, **kwargs):
                if kwargs.get("stream_to_avatar"):
                    avatar_stream.put_msg_txt(first, kwargs.get("datainfo") or {})
                    first_tts_at.append(time.perf_counter())
                    time.sleep(gap)
                    avatar_stream.put_msg_txt(second, kwargs.get("datainfo") or {})
                    return first + second
                time.sleep(gap)
                return first + second

            with patch("src.server.voice_session.llm_response", side_effect=fake_llm):
                await session.start_text_turn("請比較", interrupt=False)
                await session._turn_task
            if not first_tts_at:
                first_tts_at.append(time.perf_counter())
            await session.close()
            return len(avatar.messages), first_tts_at[0] - started_at, avatar.messages[0][0]

        stream_count, stream_first, stream_text = await run_mode(True)
        legacy_count, legacy_first, legacy_text = await run_mode(False)

        self.assertGreaterEqual(stream_count, 2)
        self.assertEqual(legacy_count, 1)
        self.assertEqual(legacy_text, first + second)
        self.assertIn(first[:8], stream_text)
        self.assertLess(stream_first, gap / 2)
        self.assertGreater(legacy_first, gap * 0.8)
        self.assertLess(stream_first, legacy_first)

    async def test_streaming_inter_fragment_gap_does_not_falsely_stall(self):
        session, avatar, events = self.make_session(streaming=True)

        def slow_streaming_llm(text, avatar_stream, **kwargs):
            datainfo = kwargs.get("datainfo") or {}
            event0 = {**datainfo, "fragment_sequence": 0}
            session.register_fragment("第一句話。", event0)
            session.on_output_audio(True)
            session.on_output_audio_frame(event0, True)
            session.on_output_audio_frame({**event0, "fragment_end": True}, True)
            # fragment 0 finishes playing, now audio is silent
            # Simulate 60 frames (1.2s) of silence while LLM is still generating
            for _ in range(60):
                session.on_output_audio(False)
            # LLM emits fragment 1 after 1.2s pause
            event1 = {**datainfo, "fragment_sequence": 1}
            session.register_fragment("第二句話。", event1)
            session.on_output_audio(True)
            session.on_output_audio_frame(event1, True)
            session.on_output_audio_frame({**event1, "fragment_end": True}, True)
            return "第一句話。第二句話。"

        with patch("src.server.voice_session.llm_response", side_effect=slow_streaming_llm):
            started = await session.start_text_turn("測試串流間隔不誤殺", interrupt=False)
            await session._turn_task

        # Turn should NOT be cancelled or errored
        errors = [item for item in events if item.get("type") == "state" and item.get("state") == "error"]
        self.assertEqual(errors, [])
        cancelled = [item for item in events if item.get("type") == "turn_cancelled"]
        self.assertEqual(cancelled, [])
        self.assertIsNotNone(session._turn_id)

        # And now all fragments end after LLM finishes
        session.on_output_audio(False)
        session.on_output_audio(False)
        session.on_output_audio(False)
        await asyncio.sleep(0.35)
        await session.close()


class WebRTCOfferCapacityTests(unittest.IsolatedAsyncioTestCase):
    async def test_offer_rejects_before_loading_when_session_capacity_is_full(self):
        from src.server.routes.webrtc import offer
        from src.server.state import state

        request = AsyncMock()
        request.json.return_value = {
            "client_role": "console",
            "sdp": "offer",
            "type": "offer",
        }
        config = SimpleNamespace(app=SimpleNamespace(max_session=1))
        with (
            patch.object(state, "model_ready", True),
            patch.object(state, "model", object()),
            patch.object(state, "avatar", object()),
            patch.object(state, "config", config),
            patch.object(state, "avatar_streams", {1: object()}),
            patch.object(state, "session_roles", {1: "console"}, create=True),
        ):
            response = await offer(request)

        self.assertEqual(response.status, 429)
        request.json.assert_awaited_once()

    async def test_console_and_stage_have_independent_capacity(self):
        from src.server.routes.webrtc import offer
        from src.server.state import state

        class ReachedOfferParsing(Exception):
            pass

        request = AsyncMock()
        request.json.return_value = {
            "client_role": "console",
            "sdp": "offer",
            "type": "offer",
        }
        config = SimpleNamespace(app=SimpleNamespace(max_session=1))
        with (
            patch.object(state, "model_ready", True),
            patch.object(state, "model", object()),
            patch.object(state, "avatar", object()),
            patch.object(state, "config", config),
            patch.object(state, "avatar_streams", {1: object()}),
            patch.object(state, "session_roles", {1: "stage"}, create=True),
            patch(
                "src.server.routes.webrtc.RTCSessionDescription",
                side_effect=ReachedOfferParsing,
            ),
        ):
            with self.assertRaises(ReachedOfferParsing):
                await offer(request)


class ChatReplyModeRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_human_chat_delegates_to_text_turn_and_returns_ack(self):
        from src.server.routes.chat import human
        from src.server.state import state

        request = AsyncMock()
        request.json.return_value = {
            "type": "chat",
            "text": "你好",
            "sessionid": 7,
            "interrupt": True,
        }
        voice_session = SimpleNamespace(
            start_text_turn=AsyncMock(
                return_value={
                    "turn_id": "turn-1",
                    "reply_mode": "streaming",
                    "delivery": "events",
                }
            ),
            interrupt=AsyncMock(),
        )
        avatar = SimpleNamespace(flush_talk=Mock())
        with (
            patch.object(state, "voice_sessions", {7: voice_session}),
            patch.object(state, "avatar_streams", {7: avatar}),
        ):
            response = await human(request)

        payload = json.loads(response.text)
        self.assertEqual(payload["code"], 0)
        self.assertEqual(payload["msg"], "accepted")
        self.assertEqual(payload["turn_id"], "turn-1")
        self.assertNotIn("response", payload)
        voice_session.start_text_turn.assert_awaited_once_with("你好", interrupt=True)
        voice_session.interrupt.assert_not_awaited()
        avatar.flush_talk.assert_not_called()

    async def test_human_chat_rejects_missing_voice_session(self):
        from aiohttp import web
        from src.server.routes.chat import human
        from src.server.state import state

        request = AsyncMock()
        request.json.return_value = {
            "type": "chat",
            "text": "你好",
            "sessionid": 99,
        }
        with patch.object(state, "voice_sessions", {}), patch.object(
            state, "avatar_streams", {}
        ):
            with self.assertRaises(web.HTTPConflict):
                await human(request)

    async def test_human_chat_rejects_when_event_sink_is_not_ready(self):
        from aiohttp import web
        from src.server.routes.chat import human
        from src.server.state import state

        request = AsyncMock()
        request.json.return_value = {
            "type": "chat",
            "text": "你好",
            "sessionid": 7,
        }
        voice_session = SimpleNamespace(event_sink_ready=False)
        with (
            patch.object(state, "voice_sessions", {7: voice_session}),
            patch.object(state, "avatar_streams", {7: object()}),
        ):
            with self.assertRaises(web.HTTPConflict):
                await human(request)


if __name__ == "__main__":
    unittest.main()
