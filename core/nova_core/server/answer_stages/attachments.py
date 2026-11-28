# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Stage: fold the session's selected attachments into the question."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Optional

from nova_core.server.answer_stages.context import AnswerInputs, StageContext


async def attachments_stage(ctx: StageContext, inputs: AnswerInputs) -> Optional[AnswerInputs]:
    """Read the selected attachments into the question; ``None`` once the turn is stale."""
    loop = asyncio.get_running_loop()
    resolved = ctx.attachments.validate_selection(ctx.attachments.selection)
    if not resolved:
        return inputs
    from nova_core.server.attachments import vision_ready
    if not await asyncio.to_thread(vision_ready, ctx.config):
        raise ValueError('vision_unavailable')
    ctx.emit('attachment_status', state='reading', total=sum(len(p) for _, p in resolved))

    def progress(index, total, source):
        loop.call_soon_threadsafe(lambda: ctx.emit(
            'attachment_status', state='analyzing', index=index, total=total, source=source)
            if ctx.is_current() else None)

    text = await asyncio.to_thread(
        ctx.attachments.prepare_question, inputs.text, resolved, ctx.avatar_config,
        progress, ctx.is_current)
    if not ctx.is_current():
        return None
    return replace(inputs, text=text)
