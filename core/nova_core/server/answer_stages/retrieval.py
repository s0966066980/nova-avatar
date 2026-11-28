# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Stage: bounded retrieval from the role's knowledge bases."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Optional

from nova_contracts.llm import RetrievalRequest
from nova_core.server.answer_stages.context import AnswerInputs, StageContext
from nova_core.utils.logging import logger


async def retrieval_stage(ctx: StageContext, inputs: AnswerInputs) -> Optional[AnswerInputs]:
    """Retrieve reference passages for the question; ``None`` once the turn is stale.

    Retrieval never blocks the answer: past its budget, or when the service fails, the
    answer goes ahead without it and says so through the result's status.
    """
    selection = ctx.rag_selection
    if not (selection["enabled"] and selection["dataset_ids"]):
        return inputs
    ctx.emit("state", state="retrieving")
    ctx.stage_start("retrieval")
    try:
        result = (await asyncio.wait_for(ctx.llm.retrieve(RetrievalRequest(
            question=str(inputs.text), dataset_ids=tuple(selection["dataset_ids"]),
            document_ids=(tuple(selection["document_ids"])
                          if selection.get("document_scope") == "selected" else ()),
        )), ctx.retrieval_budget)).model_dump(mode="json")
    except asyncio.TimeoutError:
        result = {"status": "timeout", "sources": []}
        logger.info("RAGFlow retrieval exceeded %.1fs; answering without it", ctx.retrieval_budget)
    except Exception as exc:
        result = {"status": "unavailable", "sources": []}
        logger.warning(f"RAGFlow retrieval unavailable: {type(exc).__name__}")
    ctx.stage_end("retrieval")
    if not ctx.is_current():
        return None
    return replace(inputs, rag_result=result)
