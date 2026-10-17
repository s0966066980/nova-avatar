# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Warm the local prompt prefix before the first visitor speaks."""
from __future__ import annotations

import time

from src.llm.base import load_system_prompt
from src.llm.engines.openai import OpenAILLM
from src.llm.prompts import compose_system_prompt
from src.llm.router import ReplyMode
from src.llm.rules import snapshot_from_config
from src.utils.logging import logger


def prewarm_local_llm(config, *, timeout_seconds: float = 25.0) -> bool:
    """Prefill llama.cpp using the real profile, without history or playback.

    Remote providers are skipped. Like the Orin startup path, finish one
    bounded disposable completion before declaring the prompt cache warm.
    """
    llm = config.llm
    if llm.provider != "llamacpp":
        return True
    engine = None
    started = time.monotonic()
    try:
        engine = OpenAILLM(
            config=config, api_key=llm.api_key or "llamacpp",
            base_url=llm.base_url, model=llm.model,
        )
        profile = llm.assistant_profile
        prompt = compose_system_prompt(
            load_system_prompt(config), reply_mode=ReplyMode.AUTO,
            response_max_chars=engine.response_max_chars,
            board_max_items=llm.board.max_items,
            rules=snapshot_from_config(config),
            assistant_name=profile.assistant_name,
            restriction_prompt=profile.restriction_prompt,
        )
        engine._client = engine.client.with_options(
            timeout=timeout_seconds, max_retries=0,
        )
        engine.max_tokens = 16
        chunks = engine.chat_stream(
            "請用一句短句說明如何保持專注。", system_prompt=prompt,
        )
        received = False
        try:
            for chunk in chunks:
                if time.monotonic() - started >= timeout_seconds:
                    return False
                received = received or bool(chunk)
        finally:
            chunks.close()
        logger.info("Local LLM prompt prewarm ready=%s elapsed=%.3fs",
                    received, time.monotonic() - started)
        return received
    except Exception as exc:
        logger.warning("Local LLM prewarm failed type=%s", type(exc).__name__)
        return False
    finally:
        if engine is not None and engine._client is not None:
            engine._client.close()
