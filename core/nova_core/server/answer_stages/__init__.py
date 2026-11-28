# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The stages that prepare a turn's answer, as two ordered lists.

``VoiceTurnSession`` no longer knows what attachments, retrieval or web search are;
it runs the stages listed here. Each stage is one module that works through a
``StageContext`` and can be added, changed or removed without touching the turn flow.

- ``INPUT_STAGES`` run first, before routing has chosen the role, so they can run
  beside routing (ADR 0022). They extend the question and add retrieved passages.
- ``ANSWER_STAGES`` run after routing, for the role that will answer. A stage may
  carry on with new inputs or answer with a fixed text (``Speak``).

To add a feature that needs something before the answer, write a stage module and
add it to one of these lists. To drop one, remove it from the list. A stage that
finds the turn no longer current returns ``None``.
"""

from __future__ import annotations

from typing import Optional

from nova_core.server.answer_stages.attachments import attachments_stage
from nova_core.server.answer_stages.context import (
    AnswerInputs, AnswerStage, InputStage, Speak, StageContext,
)
from nova_core.server.answer_stages import web_search
from nova_core.server.answer_stages.retrieval import retrieval_stage
from nova_core.server.answer_stages.web_search import web_search_stage

# Order matters: retrieval searches with the question the attachments extended.
INPUT_STAGES: tuple[InputStage, ...] = (attachments_stage, retrieval_stage)
ANSWER_STAGES: tuple[AnswerStage, ...] = (web_search_stage,)

__all__ = [
    "ANSWER_STAGES", "AnswerInputs", "AnswerStage", "INPUT_STAGES", "InputStage", "Speak",
    "StageContext", "run_answer_stages", "run_input_stages", "web_search",
]


async def run_input_stages(ctx: StageContext, text: str) -> Optional[AnswerInputs]:
    """The inputs of the main answer for ``text``; ``None`` once the turn is stale."""
    inputs: Optional[AnswerInputs] = AnswerInputs(text=text, rag_result=None)
    for stage in INPUT_STAGES:
        inputs = await stage(ctx, inputs)
        if inputs is None:
            return None
    return inputs


async def run_answer_stages(ctx: StageContext, inputs: AnswerInputs, question: str,
                            role_plan: Optional[dict]) -> "AnswerInputs | Speak | None":
    """Run the second phase; stops at the first stage that speaks or finds the turn stale."""
    outcome: "AnswerInputs | Speak | None" = inputs
    for stage in ANSWER_STAGES:
        outcome = await stage(ctx, inputs, question, role_plan)
        if not isinstance(outcome, AnswerInputs):
            return outcome
        inputs = outcome
    return outcome
