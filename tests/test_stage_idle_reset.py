# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Console and stage sessions forget their own conversation after sitting idle."""
from __future__ import annotations

import asyncio
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from nova_contracts.llm import SessionRef
from src.server.voice_session import VoiceTurnSession
from tests.llm_fakes import FakeLlm, answering
from tests.session_fakes import FakeStt, FakeAvatar, FakeSegmenter

DELAY = 0.08
REPLY = "還沒開始播放的回覆"


@contextmanager
def forgetting(session):
    """Watch the LLM service being told to forget this conversation."""
    forget = session._llm.clear_history = Mock()
    yield forget


class StageIdleResetTests(unittest.IsolatedAsyncioTestCase):
    def make_session(self, *, presenter="stage", seconds=DELAY, segment=None):
        config = SimpleNamespace(
            asr=SimpleNamespace(type="whisper", model_size="base", language="zh"),
            vad=SimpleNamespace(),
            reply_streaming=SimpleNamespace(enabled=False),
            stage=SimpleNamespace(idle_reset_seconds=seconds),
        )
        session = VoiceTurnSession(7, config, FakeAvatar(), presenter=presenter, llm=FakeLlm())
        session._segmenter = FakeSegmenter(segment)
        session._stt = FakeStt()
        events = []
        session.attach_event_sink(lambda raw: events.append(json.loads(raw)))
        self.addAsyncCleanup(session.close)
        return session, events

    async def finish_one_turn(self, session):
        with answering(session, REPLY):
            await session.start_text_turn("上一位訪客的問題", interrupt=False)
            await session._turn_task
        await session.interrupt()

    async def settle(self, factor=3):
        await asyncio.sleep(DELAY * factor)

    async def test_idle_stage_forgets_the_previous_visitor(self):
        session, events = self.make_session()
        with forgetting(session) as clear:
            await self.finish_one_turn(session)
            clear.assert_not_called()
            await self.settle()

        clear.assert_called_once_with(SessionRef(session_id=7))
        types = [event["type"] for event in events]
        self.assertIn("board_clear", types)
        self.assertEqual(types[-1], "conversation_reset")
        self.assertFalse(session._conversation_dirty)

    async def test_countdown_starts_only_after_the_turn_has_ended(self):
        session, _events = self.make_session()
        with forgetting(session) as clear:
            with answering(session, REPLY):
                await session.start_text_turn("問題", interrupt=False)
                await session._turn_task
                await self.settle()
            clear.assert_not_called()
            await session.interrupt()
            await self.settle()

        clear.assert_called_once_with(SessionRef(session_id=7))

    async def test_a_new_turn_cancels_the_countdown_and_restarts_it_afterwards(self):
        session, _events = self.make_session(seconds=0.2)
        with forgetting(session) as clear:
            await self.finish_one_turn(session)
            await asyncio.sleep(0.1)
            with answering(session, REPLY):
                await session.start_text_turn("下一個問題", interrupt=False)
                await session._turn_task
            await asyncio.sleep(0.3)
            clear.assert_not_called()

            await session.interrupt()
            await asyncio.sleep(0.5)

        clear.assert_called_once_with(SessionRef(session_id=7))

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
        session._stt = SimpleNamespace(transcribe=Mock())
        with forgetting(session) as clear:
            await self.finish_one_turn(session)
            await asyncio.sleep(0.1)
            session._segmenter.segment = segment
            await session.feed_pcm(np.ones(512, dtype=np.int16))
            await session._turn_task
            clear.assert_not_called()
            await asyncio.sleep(0.6)

        clear.assert_called_once_with(SessionRef(session_id=7))

    async def test_reset_happens_once_until_another_conversation_starts(self):
        session, _events = self.make_session()
        with forgetting(session) as clear:
            await self.finish_one_turn(session)
            await self.settle()
            session._refresh_gate()
            await self.settle()

        clear.assert_called_once_with(SessionRef(session_id=7))

    async def test_zero_seconds_disables_the_reset(self):
        session, _events = self.make_session(seconds=0)
        with forgetting(session) as clear:
            await self.finish_one_turn(session)
            await self.settle()

        clear.assert_not_called()

    async def test_closing_the_session_cancels_the_countdown(self):
        session, _events = self.make_session()
        with forgetting(session) as clear:
            await self.finish_one_turn(session)
            await session.close()
            await self.settle()

        clear.assert_not_called()


if __name__ == "__main__":
    unittest.main()
