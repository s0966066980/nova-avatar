# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Routing, retrieval and the main answer run concurrently (ADR 0022)."""
from __future__ import annotations

import asyncio
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.llm.history import TransactionalHistory
from src.profiles.coordinator import ANSWER_CONTEXT
from src.server.voice_session import VoiceTurnSession
from tests.test_role_coordinator import async_test, connect, field  # noqa: F401

SPECULATIVE = {"context": ANSWER_CONTEXT}
FIXED = "接下來請天氣助手為您說明。"


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _Avatar:
    def __init__(self):
        self.messages = []
        self.flushes = 0
        self.callbacks = {}

    def configure_media_fence(self, **callbacks):
        self.callbacks = callbacks

    def put_msg_txt(self, text, data=None):
        self.messages.append((text, dict(data or {})))
        queued = self.callbacks.get("on_fragment_queued")
        if queued is not None and (data or {}).get("turn_id"):
            queued(text, data)

    def flush_talk(self):
        self.flushes += 1


class _Roles:
    """The coordinator seam: a routing decision the test releases."""

    enabled = True

    def __init__(self, plan, *, clock=None, seconds=0.0, continues=False):
        self.plan = plan
        self.clock = clock
        self.seconds = seconds
        self._continues = continues
        self.continuations: dict = {}
        self.gate = asyncio.Event()
        self.started = asyncio.Event()
        self.returned = False
        self.cancelled_sids: list = []

    def continues(self, _voice, _turn_id):
        return self._continues

    def speculative_plan(self):
        return dict(SPECULATIVE)

    async def before_generate(self, _voice, _text, _turn_id, _generation):
        self.started.set()
        await self.gate.wait()
        if self.clock is not None:
            self.clock.advance(self.seconds)
        self.returned = True
        return dict(self.plan)

    def cancel(self, sid):
        self.cancelled_sids.append(sid)

    def input_allowed(self, _voice):
        return True

    def notify(self, _session=None):
        pass


class _Answer:
    """A streaming main answer driven from its worker thread."""

    def __init__(self, session, text="主回答。", *, clock=None, seconds=0.0):
        self.session = session
        self.text = text
        self.clock = clock
        self.seconds = seconds
        self.calls: list[dict] = []
        self.started = threading.Event()
        self.proceed = threading.Event()
        self.proceed.set()
        self.finished = threading.Event()
        self.order: list[str] = []

    def __call__(self, _text, avatar, **kwargs):
        self.calls.append(kwargs)
        data = kwargs["datainfo"]
        point = {"turn_id": data["turn_id"], "generation": data["generation"]}
        try:
            if self.clock is not None:
                self.clock.advance(self.seconds)
            if not kwargs["chunk_guard"](0):
                return ""
            self.session._on_llm_chunk(self.text, {**point, "llm_sequence": 0})
            avatar.put_msg_txt(self.text, {**point, "fragment_sequence": 0})
            self.started.set()
            self.proceed.wait(5)
            if not kwargs["chunk_guard"](1):
                # A fenced answer must not leave a playable fragment behind.
                avatar.put_msg_txt("殘留。", {**point, "fragment_sequence": 1})
                return ""
            return self.text
        finally:
            self.order.append("worker_done")
            self.finished.set()


def _streaming_config(**extra):
    return SimpleNamespace(
        model=SimpleNamespace(avatar_id="alpha"),
        asr=SimpleNamespace(type="whisper", model_size="base", language="zh"),
        vad=SimpleNamespace(),
        reply_streaming=SimpleNamespace(enabled=True),
        **extra,
    )


class _SessionCase(unittest.IsolatedAsyncioTestCase):
    config_extra: dict = {}

    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.avatar = _Avatar()
        self.session = VoiceTurnSession(
            95, _streaming_config(**self.config_extra), self.avatar, clock=self.clock)
        self.session._segmenter = SimpleNamespace(reset=lambda: None, is_speaking=False)
        self.session._media_player = SimpleNamespace(discard_stale_media=lambda: None)
        self.events: list[dict] = []
        self.session.attach_event_sink(lambda raw: self.events.append(json.loads(raw)))
        self._patches = [
            patch("src.server.voice_session.prepare_spoken_history"),
            patch("src.server.voice_session.discard_pending_history"),
        ]
        self.prepare_history = self._patches[0].start()
        self.discard_history = self._patches[1].start()

    async def asyncTearDown(self):
        for item in self._patches:
            item.stop()
        await self.session.close()

    def _types(self):
        return [event["type"] for event in self.events]

    def _deltas(self):
        return [e["text_delta"] for e in self.events if e["type"] == "assistant_response_delta"]

    async def _start(self, roles, answer, text="今天有什麼活動"):
        self.session._role_coordinator = roles
        self.llm = patch("src.server.voice_session.llm_response", side_effect=answer)
        self.llm.start()
        self.addCleanup(self.llm.stop)
        accepted = await self.session.start_text_turn(text, interrupt=False)
        return accepted["turn_id"], self.session._generation

    def _gate_audio(self, turn_id, generation, sequence=0):
        """Offer one synthesized PCM frame from a TTS thread."""
        results: list[bool] = []
        point = {"turn_id": turn_id, "generation": generation, "fragment_sequence": sequence}
        thread = threading.Thread(
            target=lambda: results.append(
                self.session.accepts_media(point, "avatar_audio_enqueue")),
            daemon=True,
        )
        thread.start()
        return thread, results


class GeneralTurnTests(_SessionCase):
    async def test_answer_starts_before_routing_and_audio_waits_for_the_decision(self):
        roles = _Roles(SPECULATIVE)
        answer = _Answer(self.session)
        turn_id, generation = await self._start(roles, answer)

        self.assertTrue(await asyncio.to_thread(answer.started.wait, 2))
        self.assertFalse(roles.returned, "the main answer must not wait for routing")
        thread, results = self._gate_audio(turn_id, generation)
        await asyncio.sleep(0.1)
        self.assertTrue(thread.is_alive(), "synthesized audio is held until routing decides")
        self.assertNotIn("assistant_response_start", self._types())
        self.assertEqual(self._deltas(), [])

        roles.gate.set()
        await self.session._turn_task
        await asyncio.to_thread(thread.join, 2)
        self.assertEqual(results, [True])
        self.assertEqual(self._deltas(), ["主回答。"])
        self.assertIn("assistant_response_start", self._types())
        self.assertEqual(answer.calls[0]["rag_context"].strip(), ANSWER_CONTEXT)

    async def test_first_audio_excludes_routing_time(self):
        roles = _Roles(SPECULATIVE, clock=self.clock, seconds=0.6)
        answer = _Answer(self.session, clock=self.clock, seconds=0.2)
        turn_id, generation = await self._start(roles, answer)
        self.assertTrue(await asyncio.to_thread(answer.started.wait, 2))
        thread, _ = self._gate_audio(turn_id, generation)
        await asyncio.sleep(0.05)
        roles.gate.set()
        await self.session._turn_task
        await asyncio.to_thread(thread.join, 2)
        await asyncio.sleep(0)  # deliver the thread-safe hold notification
        self.session.on_output_audio(True)

        stages = self.session.metrics_snapshot()["stage_seconds"]
        self.assertEqual(stages["pre_answer"], 0.0)
        self.assertEqual(stages["routing"], 0.8)
        # Audio was ready 0.2 s in and waited 0.6 s for the decision.
        self.assertEqual(stages["routing_hold"], 0.6)

    async def test_routing_faster_than_the_answer_costs_no_hold(self):
        roles = _Roles(SPECULATIVE)
        answer = _Answer(self.session)
        answer.proceed.clear()
        turn_id, generation = await self._start(roles, answer)
        await asyncio.to_thread(answer.started.wait, 2)
        roles.gate.set()
        await asyncio.sleep(0.05)
        thread, results = self._gate_audio(turn_id, generation)
        await asyncio.to_thread(thread.join, 2)
        self.assertEqual(results, [True])
        answer.proceed.set()
        await self.session._turn_task
        self.assertEqual(self.session.metrics_snapshot()["stage_seconds"]["routing_hold"], 0.0)

    async def test_held_turn_is_not_failed_as_a_playback_stall(self):
        roles = _Roles(SPECULATIVE)
        answer = _Answer(self.session)
        answer.proceed.clear()
        turn_id, _ = await self._start(roles, answer)
        await asyncio.to_thread(answer.started.wait, 2)
        for _ in range(2000):
            self.session.on_output_audio(False)
        self.assertEqual(self.session._turn_id, turn_id)
        self.assertNotIn("turn_cancelled", self._types())
        answer.proceed.set()
        roles.gate.set()
        await self.session._turn_task


class HandoffTurnTests(_SessionCase):
    async def test_handoff_plays_no_main_answer_audio(self):
        roles = _Roles({"fixed": FIXED, "handoff_id": "h1"})
        answer = _Answer(self.session)
        answer.proceed.clear()
        self.discard_history.side_effect = lambda *_args: answer.order.append("discard")
        self.prepare_history.side_effect = lambda *_args: answer.order.append("fixed_history")
        turn_id, generation = await self._start(roles, answer, "明天臺北會下雨嗎")
        self.assertTrue(await asyncio.to_thread(answer.started.wait, 2))
        thread, results = self._gate_audio(turn_id, generation)
        await asyncio.sleep(0.05)

        roles.gate.set()
        await asyncio.sleep(0.05)
        answer.proceed.set()
        await self.session._turn_task
        await asyncio.to_thread(thread.join, 2)

        self.assertEqual(results, [False], "held main-answer audio is dropped")
        spoken = [(text, data) for text, data in self.avatar.messages]
        self.assertEqual(spoken[-1][0], FIXED)
        self.assertGreater(spoken[-1][1]["generation"], generation)
        self.assertEqual(self.session._fragment_texts, {0: FIXED})
        self.assertNotIn("主回答。", self._deltas())
        self.assertNotIn("殘留。", self._deltas())
        self.assertEqual(self._deltas(), [FIXED])
        self.assertEqual(self._types().count("assistant_response_start"), 1)
        self.assertGreaterEqual(self.avatar.flushes, 1)
        # The speculative pending history is dropped only after its worker stopped.
        self.discard_history.assert_called_once_with(self.avatar, turn_id)
        self.assertEqual(answer.order, ["worker_done", "discard", "fixed_history"])
        new_point = {"turn_id": turn_id, "generation": self.session._generation,
                     "fragment_sequence": 0}
        self.assertTrue(self.session.accepts_media(new_point, "avatar_audio_enqueue"))

    async def test_handoff_metrics_measure_the_fixed_reply_not_the_discarded_answer(self):
        roles = _Roles({"fixed": FIXED, "handoff_id": "h1"}, clock=self.clock, seconds=0.5)
        answer = _Answer(self.session, clock=self.clock, seconds=0.2)
        await self._start(roles, answer, "明天臺北會下雨嗎")
        await asyncio.to_thread(answer.started.wait, 2)
        roles.gate.set()
        await self.session._turn_task
        stages = self.session.metrics_snapshot()["stage_seconds"]
        self.assertEqual(stages["routing"], 0.7)
        self.assertEqual(stages["pre_answer"], 0.7)
        self.assertIsNone(stages["llm_first_token"])
        self.assertIsNone(stages["routing_hold"])

    async def test_routed_context_regenerates_the_answer_without_holding_it(self):
        weather = {"status": "available", "source": "CWA", "series": {}}
        roles = _Roles({"weather": weather, "context": "已確認臺北市"})
        answer = _Answer(self.session)
        answer.proceed.clear()
        turn_id, generation = await self._start(roles, answer)
        await asyncio.to_thread(answer.started.wait, 2)
        thread, results = self._gate_audio(turn_id, generation)
        roles.gate.set()
        await asyncio.sleep(0.05)
        answer.proceed.set()
        await self.session._turn_task
        await asyncio.to_thread(thread.join, 2)

        self.assertEqual(results, [False])
        self.assertEqual(len(answer.calls), 2)
        self.assertIn("已確認臺北市", answer.calls[1]["rag_context"])
        self.assertNotIn(ANSWER_CONTEXT, answer.calls[1]["rag_context"])
        regenerated = answer.calls[1]["datainfo"]["generation"]
        self.assertGreater(regenerated, generation)
        self.assertEqual(self._deltas(), ["主回答。"])
        self.assertIn("weather_result", self._types())
        thread, results = self._gate_audio(turn_id, regenerated)
        await asyncio.to_thread(thread.join, 2)
        self.assertEqual(results, [True])

    async def test_continuation_turn_waits_for_its_handoff_plan(self):
        roles = _Roles({"weather": None, "context": "已確認的交接背景"}, continues=True)
        answer = _Answer(self.session)
        await self._start(roles, answer)
        await asyncio.sleep(0.05)
        self.assertEqual(answer.calls, [])
        roles.gate.set()
        await self.session._turn_task
        self.assertEqual(len(answer.calls), 1)
        self.assertIn("已確認的交接背景", answer.calls[0]["rag_context"])


class CancellationTests(_SessionCase):
    async def test_interrupt_during_routing_leaves_no_playable_fragment(self):
        roles = _Roles(SPECULATIVE)
        answer = _Answer(self.session)
        answer.proceed.clear()
        turn_id, generation = await self._start(roles, answer)
        await asyncio.to_thread(answer.started.wait, 2)
        thread, results = self._gate_audio(turn_id, generation)
        await asyncio.sleep(0.05)

        await self.session.interrupt()
        answer.proceed.set()
        await asyncio.to_thread(thread.join, 2)
        await asyncio.to_thread(answer.finished.wait, 2)
        await asyncio.sleep(0.05)

        self.assertEqual(results, [False])
        self.assertFalse(thread.is_alive())
        self.assertEqual(self._deltas(), [])
        self.assertNotIn("assistant_response_start", self._types())
        stale = {"turn_id": turn_id, "generation": generation, "fragment_sequence": 2}
        self.assertFalse(self.session.register_fragment("殘留。", stale))
        self.assertFalse(roles.returned)


    async def test_cancelled_plan_drops_the_held_answer(self):
        roles = _Roles({"cancelled": True})
        answer = _Answer(self.session)
        turn_id, generation = await self._start(roles, answer)
        await asyncio.to_thread(answer.started.wait, 2)
        thread, results = self._gate_audio(turn_id, generation)
        roles.gate.set()
        await self.session._turn_task
        await asyncio.to_thread(thread.join, 2)
        self.assertEqual(results, [False])
        self.assertFalse(self.session._playback_held())
        self.assertEqual(self._deltas(), [])

    async def test_input_failure_after_the_fence_ends_the_turn(self):
        roles = _Roles({"weather": None, "context": "已確認臺北市"})
        answer = _Answer(self.session)
        with patch("src.server.attachments.vision_ready", return_value=False):
            turn_id, _ = await self._start(roles, answer)
            # The turn task has not run yet: its attachment step now fails.
            self.session.attachments.validate_selection = lambda _selection: [("圖", [1])]
            await roles.started.wait()
            roles.gate.set()
            await self.session._turn_task
        self.assertIsNone(self.session._turn_id)
        errors = [e for e in self.events if e["type"] == "state" and e.get("state") == "error"]
        self.assertEqual([e["turn_id"] for e in errors], [turn_id])
        self.assertEqual(answer.calls, [])


class RetrievalBudgetTests(_SessionCase):
    config_extra = {"profile_rag": {"enabled": True, "dataset_ids": ["a" * 32]}}

    async def test_slow_retrieval_answers_without_it_and_reports_timeout(self):
        async def slow(_client, _question, _dataset_ids, **_kwargs):
            await asyncio.sleep(10)
            return {"status": "matched", "sources": [{"content": "晚到的事實"}]}

        answer = _Answer(self.session)
        with patch("src.server.voice_session.RagFlowClient.retrieve", slow), patch(
            "src.server.voice_session.RETRIEVAL_BUDGET_SECONDS", 0.05
        ):
            await self._start(None, answer)
            await asyncio.wait_for(self.session._turn_task, 2)

        self.assertEqual(len(answer.calls), 1)
        self.assertNotIn("rag_context", answer.calls[0])
        statuses = [e["status"] for e in self.events if e["type"] == "rag_retrieval"]
        self.assertEqual(statuses, ["timeout"])
        self.assertIsNotNone(self.session.metrics_snapshot()["stage_seconds"]["retrieval"])

    async def test_retrieval_within_budget_is_used(self):
        async def fast(_client, _question, _dataset_ids, **_kwargs):
            return {"status": "matched", "sources": [{
                "content": "可查的事實", "document_name": "手冊",
                "document_id": "d", "dataset_id": "a" * 32}]}

        answer = _Answer(self.session)
        with patch("src.server.voice_session.RagFlowClient.retrieve", fast):
            await self._start(None, answer)
            await self.session._turn_task
        self.assertIn("可查的事實", answer.calls[0]["rag_context"])

    async def test_held_retrieval_sources_are_dropped_with_a_handoff(self):
        async def fast(_client, _question, _dataset_ids, **_kwargs):
            return {"status": "matched", "sources": [{
                "content": "可查的事實", "document_name": "手冊",
                "document_id": "d", "dataset_id": "a" * 32}]}

        roles = _Roles({"fixed": FIXED, "handoff_id": "h1"})
        answer = _Answer(self.session)
        with patch("src.server.voice_session.RagFlowClient.retrieve", fast):
            await self._start(roles, answer)
            await asyncio.to_thread(answer.started.wait, 2)
            roles.gate.set()
            await self.session._turn_task
        self.assertNotIn("rag_retrieval", self._types())


@async_test
async def test_main_role_answer_route_equals_the_speculative_plan(field):
    field.router = Mock(return_value={"route": "answer", "context": "訪客想了解服務"})
    voice, _ = connect(field)
    roles = voice._role_coordinator
    try:
        voice._turn_id = "t"
        voice._start_turn_context("t")
        assert not roles.continues(voice, "t")
        plan = await roles.before_generate(voice, "介紹你們的服務", "t", voice._generation)
        assert plan == roles.speculative_plan() == SPECULATIVE
    finally:
        await voice.close()


@async_test
async def test_general_turn_with_real_roles_delivers_the_concurrent_answer_once(field, monkeypatch):
    field.router = Mock(return_value={"route": "answer", "context": ""})
    voice, events = connect(field)
    llm = Mock(return_value="主角色的回答")
    monkeypatch.setattr("src.server.voice_session.llm_response", llm)
    try:
        await voice.start_text_turn("介紹你們的服務")
        await voice._turn_task
        llm.assert_called_once()
        assert ANSWER_CONTEXT in llm.call_args.kwargs["rag_context"]
        assert [text for text, _ in voice.avatar.messages] == ["主角色的回答"]
        assert [e["text"] for e in events if e["type"] == "assistant_response"] == ["主角色的回答"]
        assert voice._role_coordinator.phase == "ready"
    finally:
        await voice.close()


class HistoryDiscardTests(unittest.TestCase):
    def test_discarding_a_pending_turn_leaves_history_unchanged(self):
        history = TransactionalHistory(max_turns=4)
        history.begin("問題", turn_id="t")
        self.assertTrue(history.discard_pending("t"))
        self.assertFalse(history.discard_pending("t"))
        self.assertEqual(history.snapshot(), [])
        history.begin("問題", turn_id="t")  # the fixed reply may now own the turn


if __name__ == "__main__":
    unittest.main()
