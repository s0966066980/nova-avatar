# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Stage: bounded web search before the answer (ADR 0024)."""

from __future__ import annotations

import asyncio
import re
from typing import Optional

from nova_contracts.llm import WebSearchPlanRequest, WebSearchRequest, WebSearchResult, WebSummaryRequest
from nova_core.server.answer_stages.context import AnswerInputs, Speak, StageContext
from nova_core.server.web_evidence import public_result
from nova_core.utils.logging import logger
from nova_llm.config_section import llm_settings

# An explicit request to look again always wins over a model's accidental reuse decision.
_REFRESH = re.compile(r'最新|重新|再查|重查|latest|refresh|search again|up.to.date', re.I)


async def search(ctx: StageContext, inputs: AnswerInputs, question: str,
                 role_plan: Optional[dict]) -> Optional[AnswerInputs]:
    """Search only after routing, using the raw question, never attachment/RAG text.

    Returns the inputs with the search result, its selected evidence and any quote
    that answers the question by itself; ``None`` once the turn is no longer current.
    """
    policy = getattr(ctx.config, 'profile_web_search', {})
    if not policy.get('enabled') or (role_plan and role_plan.get('weather') is not None):
        return inputs
    role = getattr(ctx.config, 'profile_id', '')
    previous = ctx.web_cache.previous(role, policy)
    ctx.emit('state', state='search_planning')
    ctx.stage_start('web_search_plan')
    try:
        decision = (await ctx.llm.plan_web_search(WebSearchPlanRequest(
            settings=llm_settings(ctx.config), question=str(question),
            previous_queries=(previous['query'],) if previous else ()))).model_dump()
    except asyncio.CancelledError:
        raise
    except Exception:
        decision = None
    ctx.stage_end('web_search_plan')
    if not ctx.is_current():
        return None
    if decision is not None and not decision['search']:
        return inputs
    ctx.emit('state', state='searching')
    ctx.stage_start('web_search')
    refresh = bool(_REFRESH.search(question))
    if decision is None:
        result = {'status': 'planning_failed', 'query': '', 'sources': [], 'reused': False}
    elif previous and decision['reuse'] and not refresh:
        result = {**previous, 'reused': True}
    else:
        result = (await ctx.llm.search_web(WebSearchRequest(
            query=decision['query'], allowed_domains=tuple(policy.get('allowed_domains', []))
        ))).model_dump(mode='json')
    ctx.stage_end('web_search')
    if not ctx.is_current():
        return None
    if not result.get('reused'):
        ctx.web_cache.put(role, policy, result)
    ctx.emit('web_search_result', **public_result(result))
    selection = quote = None
    if result.get('sources') and not ctx.attachments.selection:
        ctx.emit('state', state='summarizing')
        ctx.stage_start('web_synthesis')
        try:
            summary = await asyncio.wait_for(ctx.llm.summarize_web(WebSummaryRequest(
                settings=llm_settings(ctx.config), question=str(question),
                result=WebSearchResult.model_validate(result),
                locale=ctx.locale)), 4)
            selection = summary.selection.model_dump(mode='json')
            quote = summary.quote
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning('Web evidence selection failed: %s', type(exc).__name__)
            # Never fall back to reading unsorted pages after a failed selection.
            selection = {'mode': 'unavailable', 'items': []}
        ctx.stage_end('web_synthesis')
        if not ctx.is_current():
            return None
    return AnswerInputs(inputs.text, inputs.rag_result, result, selection, quote)


def fixed_reply(ctx: StageContext, inputs: AnswerInputs) -> Optional[str]:
    """The text to say when the search leaves nothing the model may answer from.

    A small model must not be trusted to avoid inventing current facts after an
    empty or failed search, so these localized replies are authoritative.
    """
    english = ctx.locale == 'en-US'
    if inputs.web_selection is not None and not inputs.web_selection.get('items'):
        return ('I found web sources, but could not organize enough reliable evidence to answer this question.'
                if english else '已找到網頁來源，但目前未能整理出足以可靠回答這個問題的資料。')
    if inputs.web_quote is not None:
        return inputs.web_quote
    if inputs.web_result is not None and not inputs.web_result.get('sources'):
        return ('I could not retrieve usable web sources, so the latest information '
                'has not been verified. Please try again later.'
                if english else '目前未能取得可用的網路資料，最新資訊尚未查證，請稍後再試。')
    return None


async def web_search_stage(ctx: StageContext, inputs: AnswerInputs, question: str,
                           role_plan: Optional[dict]) -> "AnswerInputs | Speak | None":
    found = await search(ctx, inputs, question, role_plan)
    if found is None:
        return None
    reply = fixed_reply(ctx, found)
    return Speak(reply) if reply is not None else found

