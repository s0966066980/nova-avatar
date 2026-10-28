# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""A stage session forgets the previous visitor after the conversation sits idle."""
from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from src.server.voice_session import VoiceTurnSession
from src.llm import service as llm_service
from src.llm.engines.openai import OpenAILLM
from src.llm.response_protocol import BoardItem, SessionBoardContext
from tests.test_voice_session import FakeASR, FakeAvatar, FakeSegmenter

DELAY = 0.08
REPLY = "還沒開始播放的回覆"


class StageIdleResetTests(unittest.IsolatedAsyncioTestCase):
    def make_session(self, *, presenter="stage", seconds=DELAY, segment=None):
        config = SimpleNamespace(
            asr=SimpleNamespace(type="whisper", model_size="base", language="zh"),
            vad=SimpleNamespace(),
            reply_streaming=SimpleNamespace(enabled=False),
            stage=SimpleNamespace(idle_reset_seconds=seconds),
        )
        session = VoiceTurnSession(7, config, FakeAvatar(), presenter=presenter)
        session._segmenter = FakeSegmenter(segment)
        session._asr = FakeASR()
        session._full_reset_delay = Mock(return_value=max(seconds * 2, DELAY * 2))
        events = []
        session.attach_event_sink(lambda raw: events.append(json.loads(raw)))
        self.addAsyncCleanup(session.close)
        return session, events

    async def test_short_idle_only_clears_visible_answers(self):
        session, events = self.make_session()
        session._full_reset_delay.return_value = 1
        with patch('src.server.voice_session.clear_session_history') as clear:
            await self.finish_one_turn(session)
            await asyncio.sleep(DELAY * 1.5)
            self.assertIn('answer_clear', [event['type'] for event in events])
            self.assertNotIn('conversation_reset', [event['type'] for event in events])
            clear.assert_not_called()
            self.assertTrue(session._conversation_dirty)

    async def test_upload_busy_pauses_both_deadlines(self):
        session, events = self.make_session()
        session._attachment_busy = 1
        session.note_interaction()
        await self.settle()
        self.assertNotIn('answer_clear', [event['type'] for event in events])
        self.assertNotIn('conversation_reset', [event['type'] for event in events])
        session._attachment_busy = 0
        session.note_interaction()
        await self.settle()
        self.assertIn('conversation_reset', [event['type'] for event in events])

    async def finish_one_turn(self, session):
        with patch("src.server.voice_session.llm_response", return_value=REPLY):
            await session.start_text_turn("上一位訪客的問題", interrupt=False)
            await session._turn_task
        await session.interrupt()

    async def settle(self, factor=3):
        await asyncio.sleep(DELAY * factor)

    async def test_idle_stage_forgets_the_previous_visitor(self):
        session, events = self.make_session()
        with patch("src.server.voice_session.clear_session_history") as clear:
            await self.finish_one_turn(session)
            clear.assert_not_called()
            await self.settle()

        clear.assert_called_once_with(7)
        types = [event["type"] for event in events]
        self.assertIn("board_clear", types)
        self.assertEqual(types[-1], "conversation_reset")
        self.assertFalse(session._conversation_dirty)

    async def test_countdown_starts_only_after_the_turn_has_ended(self):
        session, _events = self.make_session()
        with patch("src.server.voice_session.clear_session_history") as clear:
            with patch("src.server.voice_session.llm_response", return_value=REPLY):
                await session.start_text_turn("問題", interrupt=False)
                await session._turn_task
                await self.settle()
            clear.assert_not_called()
            await session.interrupt()
            await self.settle()

        clear.assert_called_once_with(7)

    async def test_console_session_never_resets(self):
        session, events = self.make_session(presenter="console")
        with patch("src.server.voice_session.clear_session_history") as clear:
            await self.finish_one_turn(session)
            await self.settle()

        clear.assert_not_called()
        self.assertNotIn("conversation_reset", [event["type"] for event in events])

    async def test_a_new_turn_cancels_the_countdown_and_restarts_it_afterwards(self):
        session, _events = self.make_session(seconds=0.2)
        with patch("src.server.voice_session.clear_session_history") as clear:
            await self.finish_one_turn(session)
            await asyncio.sleep(0.1)
            with patch("src.server.voice_session.llm_response", return_value=REPLY):
                await session.start_text_turn("下一個問題", interrupt=False)
                await session._turn_task
            await asyncio.sleep(0.3)
            clear.assert_not_called()

            await session.interrupt()
            await asyncio.sleep(0.5)

        clear.assert_called_once_with(7)

    async def test_rejected_noise_does_not_leave_the_old_conversation_in_place(self):
        segment = SimpleNamespace(
            audio=np.ones(16000, dtype=np.int16) * 600,
            sample_rate=16000,
            speech_ms=200,
        )
        session, _events = self.make_session(seconds=0.25, segment=segment)
        session.config.asr = SimpleNamespace(
            min_speech_ms=450, min_audio_rms=0.003, min_confidence=0.35
        )
        session._asr = SimpleNamespace(transcribe=Mock())
        with patch("src.server.voice_session.clear_session_history") as clear:
            await self.finish_one_turn(session)
            await asyncio.sleep(0.1)
            session._segmenter.segment = segment
            await session.feed_pcm(np.ones(512, dtype=np.int16))
            await session._turn_task
            clear.assert_not_called()
            await asyncio.sleep(0.6)

        clear.assert_called_once_with(7)

    async def test_reset_happens_once_until_another_conversation_starts(self):
        session, _events = self.make_session()
        with patch("src.server.voice_session.clear_session_history") as clear:
            await self.finish_one_turn(session)
            await self.settle()
            session._refresh_gate()
            await self.settle()

        clear.assert_called_once_with(7)

    async def test_zero_seconds_disables_the_reset(self):
        session, _events = self.make_session(seconds=0)
        with patch("src.server.voice_session.clear_session_history") as clear:
            await self.finish_one_turn(session)
            await self.settle()

        clear.assert_not_called()

    async def test_closing_the_session_cancels_the_countdown(self):
        session, _events = self.make_session()
        with patch("src.server.voice_session.clear_session_history") as clear:
            await self.finish_one_turn(session)
            await session.close()
            await self.settle()

        clear.assert_not_called()

    async def test_normal_playback_and_tail_guard_finish_before_reset_in_jetson_modes(self):
        for presentation in ("musetalk", "prerecorded"):
            for reply_mode in ("legacy", "streaming", "read_aloud"):
                with self.subTest(presentation=presentation, reply_mode=reply_mode):
                    session, events = self.make_session()
                    session.config.model = SimpleNamespace(
                        avatar_id="avatar", presentation_modes={"avatar": presentation},
                    )
                    session.config.reply_streaming.enabled = reply_mode == "streaming"

                    def reply(_text, avatar, **kwargs):
                        if kwargs["stream_to_avatar"]:
                            avatar.put_msg_txt(REPLY, kwargs["datainfo"])
                        return REPLY

                    with patch("src.server.voice_session.clear_session_history") as clear:
                        if reply_mode == "read_aloud":
                            await session.start_read_aloud_turn(REPLY)
                        else:
                            with patch("src.server.voice_session.llm_response", side_effect=reply):
                                await session.start_text_turn("上一位訪客的問題")
                                await session._turn_task
                        eventpoint = session.avatar.messages[0][1]
                        session.on_output_audio(True)
                        session.on_output_audio_frame(eventpoint, True)
                        session.on_output_audio_frame({**eventpoint, "fragment_end": True}, True)
                        session.on_output_audio_clock(True, 1.0, eventpoint)
                        await self.settle()
                        clear.assert_not_called()
                        for _ in range(3):
                            session.on_output_audio(False)
                        session.on_output_audio_clock(False, 1.1, eventpoint)
                        await asyncio.sleep(DELAY)
                        clear.assert_not_called()
                        await session._tail_task
                        clear.assert_not_called()
                        await self.settle()
                        clear.assert_called_once_with(7)

                    self.assertEqual(events[-1]["type"], "conversation_reset")
                    self.assertTrue(session._gate_open)
                    await session.close()

    async def test_reset_clears_real_history_and_board_only_for_the_stage_session(self):
        session, _events = self.make_session()
        stage_llm = OpenAILLM(api_key="local-test")
        console_llm = OpenAILLM(api_key="local-test")
        board = SessionBoardContext(
            turn_id="old-visitor", title="訪客資料", summary=None,
            items=[BoardItem(title="第一項", content="舊內容")],
        )
        for llm in (stage_llm, console_llm):
            llm.add_to_history("user", "上一位訪客的問題")
            llm.queue_board_for_display(board)
            llm.acknowledge_board_display(
                turn_id=board.turn_id, board_id=board.turn_id, item_index=0,
            )
        receipt = (board.turn_id, board.turn_id, 0, "stage")
        session._board_display_receipts.add(receipt)
        with patch.dict(llm_service._session_llm_instances, {7: stage_llm, 8: console_llm}, clear=True):
            await self.finish_one_turn(session)
            await self.settle()
            self.assertEqual(stage_llm.conversation_history, [])
            self.assertIsNone(stage_llm.get_last_board())
            self.assertEqual(session._board_display_receipts, set())
            # A delayed receipt cannot bring the previous visitor's board back.
            stage_llm.acknowledge_board_display(
                turn_id=board.turn_id, board_id=board.turn_id, item_index=0,
            )
            self.assertIsNone(stage_llm.get_last_board())
            self.assertTrue(console_llm.conversation_history)
            self.assertIsNotNone(console_llm.get_last_board())
            await session.close()
            self.assertEqual(stage_llm.conversation_history, [])

    async def test_reset_preserves_manual_pause(self):
        session, events = self.make_session()
        with patch("src.server.voice_session.clear_session_history") as clear:
            await self.finish_one_turn(session)
            session.handle_control(json.dumps({"type": "capture", "enabled": False}))
            await self.settle()
        clear.assert_called_once_with(7)
        self.assertEqual(events[-1]["type"], "conversation_reset")
        self.assertFalse(session._gate_open)
        self.assertFalse(session._capture_requested)
        self.assertTrue(session._manual_pause)


if __name__ == "__main__":
    unittest.main()
