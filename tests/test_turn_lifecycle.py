# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""A turn always reaches an end, and per-turn state never grows without bound."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.server.reply_streaming.circuit_breaker import ReplyCircuitBreaker
from src.server.voice_session import VoiceTurnSession
from src.tts.base import sanitize_speech_text


class SanitizingAvatar:
    """Mirror BaseAvatar.put_msg_txt: unspeakable text never becomes a fragment."""

    def __init__(self):
        self.messages = []
        self.on_fragment_queued = None

    def put_msg_txt(self, text, data=None):
        text = sanitize_speech_text(text)
        if not text:
            return
        eventpoint = dict(data or {})
        self.messages.append((text, eventpoint))
        if self.on_fragment_queued is not None and eventpoint.get("turn_id"):
            self.on_fragment_queued(text, eventpoint)

    def flush_talk(self):
        pass

    def configure_media_fence(self, *, on_fragment_queued=None, **_unused):
        self.on_fragment_queued = on_fragment_queued


def make_session(*, streaming):
    config = SimpleNamespace(
        asr=SimpleNamespace(type="whisper", model_size="base", language="zh"),
        vad=SimpleNamespace(),
        reply_streaming=SimpleNamespace(enabled=streaming),
    )
    avatar = SanitizingAvatar()
    session = VoiceTurnSession(7, config, avatar)
    events = []
    session.attach_event_sink(lambda raw: events.append(json.loads(raw)))
    return session, avatar, events


class SilentReplyTests(unittest.IsolatedAsyncioTestCase):
    async def assert_turn_ends_without_audio(self, session, events, started):
        self.assertIsNone(session._turn_id)
        committed = [item for item in events if item["type"] == "turn_committed"]
        self.assertEqual([item["turn_id"] for item in committed], [started["turn_id"]])
        self.assertEqual(events[-1].get("state"), "listening")
        # The next question is accepted without having to interrupt anything.
        with patch("src.server.voice_session.llm_response", return_value=""):
            following = await session.start_text_turn("下一題", interrupt=False)
            await session._turn_task
        self.assertNotEqual(following["turn_id"], started["turn_id"])

    async def test_streaming_board_only_reply_ends_the_turn(self):
        session, avatar, events = make_session(streaming=True)

        def board_only(_text, _avatar, **_kwargs):
            # The board went out through on_board; no speakable fragment did.
            return "看板：營業時間"

        with patch("src.server.voice_session.llm_response", side_effect=board_only):
            started = await session.start_text_turn("營業時間？", interrupt=False)
            await session._turn_task

        self.assertEqual(avatar.messages, [])
        await self.assert_turn_ends_without_audio(session, events, started)
        await session.close()

    async def test_legacy_reply_with_no_speakable_text_ends_the_turn(self):
        session, avatar, events = make_session(streaming=False)

        with patch("src.server.voice_session.llm_response", return_value="😀😀"):
            started = await session.start_text_turn("笑一個", interrupt=False)
            await session._turn_task

        self.assertEqual(avatar.messages, [])
        await self.assert_turn_ends_without_audio(session, events, started)
        await session.close()

    async def test_read_aloud_of_unspeakable_text_ends_the_turn(self):
        session, avatar, events = make_session(streaming=False)

        started = await session.start_read_aloud_turn("👍", interrupt=False)

        self.assertEqual(avatar.messages, [])
        await self.assert_turn_ends_without_audio(session, events, started)
        await session.close()


class StreamingCircuitTests(unittest.IsolatedAsyncioTestCase):
    def make_breaker(self):
        now = [0.0]
        breaker = ReplyCircuitBreaker(clock=lambda: now[0], cooldown_seconds=60.0)
        for _ in range(3):
            breaker.mode_for_next_turn()
            breaker.record_pipeline_error()
        return breaker, now

    def test_open_circuit_retries_streaming_after_cooldown_and_closes_on_success(self):
        breaker, now = self.make_breaker()
        self.assertEqual(breaker.mode_for_next_turn(), "legacy")
        now[0] = 59.0
        self.assertEqual(breaker.mode_for_next_turn(), "legacy")

        now[0] = 61.0
        self.assertEqual(breaker.mode_for_next_turn(), "streaming")
        breaker.record_turn_success()

        self.assertFalse(breaker.is_open)
        self.assertEqual(breaker.mode_for_next_turn(), "streaming")

    def test_failed_retry_reopens_for_a_full_cooldown(self):
        breaker, now = self.make_breaker()
        now[0] = 61.0
        self.assertEqual(breaker.mode_for_next_turn(), "streaming")
        breaker.record_pipeline_error()

        now[0] = 100.0
        self.assertEqual(breaker.mode_for_next_turn(), "legacy")
        now[0] = 122.0
        self.assertEqual(breaker.mode_for_next_turn(), "streaming")

    def test_legacy_turn_success_does_not_close_an_open_circuit(self):
        breaker, now = self.make_breaker()
        self.assertEqual(breaker.mode_for_next_turn(), "legacy")
        breaker.record_turn_success()
        self.assertTrue(breaker.is_open)

    async def test_greeting_playback_failures_do_not_open_the_circuit(self):
        session, _avatar, _events = make_session(streaming=True)
        session.greetings.finished = lambda **_kwargs: None
        for _ in range(3):
            session.start_greeting("歡迎光臨")
            session._fail_playback_turn()

        self.assertFalse(session._circuit_breaker.is_open)
        started = await session.start_text_turn("你好", interrupt=False)
        self.assertEqual(started["reply_mode"], "streaming")
        await session.close()


class MicrophoneTrackLossTests(unittest.IsolatedAsyncioTestCase):
    async def test_track_error_reports_the_connection_lost(self):
        session, _avatar, events = make_session(streaming=True)
        lost = asyncio.Event()

        class BrokenTrack:
            async def recv(self):
                raise RuntimeError("decoder failed")

        session.start_track(BrokenTrack(), on_lost=lost.set)

        await asyncio.wait_for(lost.wait(), 1)
        self.assertEqual(events[-1].get("state"), "reconnecting")
        await session.close()

    async def test_cancelled_track_is_not_reported_lost(self):
        session, _avatar, _events = make_session(streaming=True)
        lost = []

        class QuietTrack:
            async def recv(self):
                await asyncio.Event().wait()

        session.start_track(QuietTrack(), on_lost=lambda: lost.append(True))
        await asyncio.sleep(0)
        await session.close()
        await asyncio.sleep(0)

        self.assertEqual(lost, [])


class SessionTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_cancels_work_started_by_control_messages(self):
        session, _avatar, _events = make_session(streaming=True)
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def slow_settings(_values):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        session.apply_conversation = slow_settings
        session.handle_control(json.dumps({"type": "conversation_settings", "settings": {}}))
        await asyncio.wait_for(started.wait(), 1)

        await session.close()

        await asyncio.wait_for(cancelled.wait(), 1)

    async def test_second_finalize_cannot_orphan_the_running_one(self):
        session, _avatar, _events = make_session(streaming=True)
        release = __import__("threading").Event()
        flushes = []

        class SlowSegmenter:
            is_speaking = False

            def flush(self):
                flushes.append(True)
                release.wait(1)
                return []

            def reset(self):
                pass

        session._segmenter = SlowSegmenter()
        session._gate_open = True
        finalize = json.dumps({"type": "capture", "enabled": False, "finalize": True})
        session.handle_control(finalize)
        running = session._finalize_task
        session._gate_open = True
        session.handle_control(finalize)

        self.assertIs(session._finalize_task, running)
        release.set()
        await running
        self.assertIsNone(session._finalize_task)
        self.assertEqual(flushes, [True])
        await session.close()


class PerTurnMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_long_running_session_keeps_bounded_turn_bookkeeping(self):
        session, _avatar, _events = make_session(streaming=False)
        with patch("src.server.voice_session.llm_response", return_value=""), \
                patch("src.server.voice_session.acknowledge_session_board_item", return_value=True):
            for index in range(300):
                await session.start_text_turn(f"問題 {index}", interrupt=False)
                await session._turn_task
                session._acknowledge_board(
                    {"turn_id": session._turn_context.turn_id,
                     "board_id": session._turn_context.turn_id,
                     "item_index": 0, "presenter": "console"},
                    presenter="console",
                )

        self.assertLessEqual(len(session._history_finalized_turns), 64)
        self.assertLessEqual(len(session._metrics_emitted_turns), 64)
        self.assertLessEqual(len(session._board_display_receipts), 256)
        await session.close()

    def test_avatar_media_sequences_do_not_grow_per_turn(self):
        from src.avatars.base import BaseAvatar
        from threading import RLock

        avatar = BaseAvatar.__new__(BaseAvatar)
        avatar._media_guard = None
        avatar._media_sequence_lock = RLock()
        avatar._media_sequences = {}
        avatar.audio_stream = SimpleNamespace(put_audio_frame=lambda *_args: False)

        for turn in range(200):
            for _ in range(3):
                avatar.put_audio_frame(
                    b"",
                    {"turn_id": f"turn-{turn}", "generation": 0, "fragment_sequence": 0},
                )
            frames = []
            avatar.audio_stream = SimpleNamespace(
                put_audio_frame=lambda _chunk, eventpoint: frames.append(eventpoint) or False
            )
        avatar.put_audio_frame(b"", {"turn_id": "turn-199", "generation": 0, "fragment_sequence": 0})

        self.assertEqual(frames[-1]["media_sequence"], 3)
        self.assertLessEqual(len(avatar._media_sequences), 8)


if __name__ == "__main__":
    unittest.main()
