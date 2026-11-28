# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The answer stages are two plain lists: a stage can be added, dropped or short-circuit the turn."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

from nova_core.server import answer_stages
from nova_core.server.answer_stages import AnswerInputs, Speak, run_answer_stages, run_input_stages
from nova_core.server.answer_stages.attachments import attachments_stage
from nova_core.server.answer_stages.retrieval import retrieval_stage
from nova_core.server.answer_stages.web_search import fixed_reply, web_search_stage

CTX = SimpleNamespace(locale="zh-TW")


def test_the_shipped_stages_and_their_order():
    # Retrieval searches with the question the attachments extended.
    assert answer_stages.INPUT_STAGES == (attachments_stage, retrieval_stage)
    assert answer_stages.ANSWER_STAGES == (web_search_stage,)


def test_input_stages_run_in_order_and_each_extends_the_inputs(monkeypatch):
    async def run():
        async def add_context(ctx, inputs):
            return replace(inputs, text=inputs.text + " +context")

        async def add_retrieval(ctx, inputs):
            return replace(inputs, rag_result={"status": "matched", "sources": [inputs.text]})

        monkeypatch.setattr(answer_stages, "INPUT_STAGES", (add_context, add_retrieval))
        inputs = await run_input_stages(CTX, "question")
        assert inputs == AnswerInputs("question +context", {"status": "matched", "sources": ["question +context"]})

    asyncio.run(run())


def test_a_stale_turn_stops_the_input_stages(monkeypatch):
    async def run():
        calls = []

        async def stale(ctx, inputs):
            calls.append("stale")

        async def never(ctx, inputs):
            calls.append("never")
            return inputs

        monkeypatch.setattr(answer_stages, "INPUT_STAGES", (stale, never))
        assert await run_input_stages(CTX, "question") is None
        assert calls == ["stale"]

    asyncio.run(run())


def test_with_no_stages_the_question_goes_through_unchanged(monkeypatch):
    async def run():
        monkeypatch.setattr(answer_stages, "INPUT_STAGES", ())
        monkeypatch.setattr(answer_stages, "ANSWER_STAGES", ())
        inputs = await run_input_stages(CTX, "question")
        assert inputs == AnswerInputs("question", None)
        assert await run_answer_stages(CTX, inputs, "question", None) is inputs

    asyncio.run(run())


def test_a_new_answer_stage_is_just_another_entry_in_the_list(monkeypatch):
    async def run():
        seen = []

        async def note_role(ctx, inputs, question, role_plan):
            seen.append((question, role_plan))
            return replace(inputs, text=inputs.text + "!")

        monkeypatch.setattr(answer_stages, "ANSWER_STAGES", (note_role,))
        outcome = await run_answer_stages(CTX, AnswerInputs("hi", None), "hi", {"role": "a"})
        assert outcome == AnswerInputs("hi!", None)
        assert seen == [("hi", {"role": "a"})]

    asyncio.run(run())


def test_a_stage_that_speaks_ends_the_stages(monkeypatch):
    async def run():
        async def speak(ctx, inputs, question, role_plan):
            return Speak("fixed")

        async def never(ctx, inputs, question, role_plan):
            raise AssertionError("a stage after Speak must not run")

        monkeypatch.setattr(answer_stages, "ANSWER_STAGES", (speak, never))
        assert await run_answer_stages(CTX, AnswerInputs("hi", None), "hi", None) == Speak("fixed")

    asyncio.run(run())


def test_a_stale_turn_stops_the_answer_stages(monkeypatch):
    async def run():
        async def stale(ctx, inputs, question, role_plan):
            return None

        monkeypatch.setattr(answer_stages, "ANSWER_STAGES", (stale,))
        assert await run_answer_stages(CTX, AnswerInputs("hi", None), "hi", None) is None

    asyncio.run(run())


def test_the_web_search_fixed_replies_follow_the_evidence():
    base = AnswerInputs("q", None)
    assert fixed_reply(CTX, base) is None
    assert "未能整理出" in fixed_reply(CTX, replace(base, web_selection={"mode": "x", "items": []}))
    assert fixed_reply(CTX, replace(base, web_selection={"items": [1]}, web_quote="the quote")) == "the quote"
    assert "最新資訊尚未查證" in fixed_reply(CTX, replace(base, web_result={"sources": []}))
    english = SimpleNamespace(locale="en-US")
    assert fixed_reply(english, replace(base, web_result={"sources": []})).startswith("I could not retrieve")
