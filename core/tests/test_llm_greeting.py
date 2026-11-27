# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The LLM layer's AI greeting entry: one plain greeting within the requested length, or an error."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from src.config.schema import Config
from src.llm.greeting import GreetingGenerationError, generate_greeting


def test_a_greeting_out_of_range_is_regenerated_once_with_a_correction():
    generate = AsyncMock(side_effect=["- 清單", "歡迎  來參觀！"])

    text = asyncio.run(generate_greeting(Config(), "介紹服務", min_chars=4, max_chars=8, generate=generate))

    assert text == "歡迎 來參觀！"
    retry = generate.await_args_list[1].args[1]
    assert retry[-1]["content"].startswith("介紹服務\n") and "字數範圍" in retry[-1]["content"]


def test_a_greeting_that_never_fits_is_an_error_without_provider_details():
    generate = AsyncMock(side_effect=RuntimeError("SECRET https://private.example"))

    with pytest.raises(GreetingGenerationError, match="^AI 招呼生成失敗，已略過本次$"):
        asyncio.run(generate_greeting(Config(), "介紹", min_chars=4, max_chars=8, generate=generate))
