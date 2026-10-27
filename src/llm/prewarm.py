# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Prefill the selected local model without recording a conversation."""
from __future__ import annotations

import time

from src.llm.base import load_system_prompt
from src.llm.engines.openai import OpenAILLM
from src.llm.prompts import compose_system_prompt
from src.llm.router import ReplyMode
from src.llm.rules import snapshot_from_config
from src.llm.llamacpp_protocol import LFM_REASONING_BUDGET, is_lfm25_reasoning
from src.utils.logging import logger


def prewarm_local_llm(config, *, timeout_seconds: float = 25.0) -> bool:
    """Use the real profile/protocol prefix; never touch session history.

    Cloud providers are excluded. Completion and networking are bounded, and
    no warmup text is sent to an avatar, subtitle, board or conversation log.
    """
    llm = config.llm
    if llm.provider != "llamacpp":
        return True
    started = time.monotonic()
    engine = None
    try:
        engine = OpenAILLM(
            config=config,
            api_key=llm.api_key or "llamacpp",
            base_url=llm.base_url,
            model=llm.model,
        )
        profile = llm.assistant_profile
        engine.observe_context = False
        prompt = compose_system_prompt(
            load_system_prompt(config),
            reply_mode=ReplyMode.AUTO,
            response_max_chars=engine.response_max_chars,
            board_max_items=llm.board.max_items,
            rules=snapshot_from_config(config),
            assistant_name=profile.assistant_name,
            restriction_prompt=profile.restriction_prompt,
        )
        # This disposable client has no production history or side effects.
        engine._client = engine.client.with_options(
            timeout=timeout_seconds, max_retries=0,
        )
        # A reasoning-only response is deliberately invisible to chat_stream.
        # LFM needs its bounded thinking allowance plus the visible envelope;
        # 16 tokens can never establish conversation readiness for this model.
        engine.max_tokens = LFM_REASONING_BUDGET + 32 if is_lfm25_reasoning(llm.model) else 16
        received = False
        chunks = engine.chat_stream(
            "請用一句短句說明如何保持專注。", system_prompt=prompt,
        )
        try:
            for chunk in chunks:
                received = received or bool(chunk)
                if time.monotonic() - started >= timeout_seconds:
                    return False
        finally:
            chunks.close()
        logger.info(
            "Local LLM prompt prewarm ready=%s elapsed=%.3fs",
            received, time.monotonic() - started,
        )
        return received
    except Exception as exc:
        logger.warning("Local LLM prewarm failed type=%s", type(exc).__name__)
        return False
    finally:
        if engine is not None and engine._client is not None:
            engine._client.close()
