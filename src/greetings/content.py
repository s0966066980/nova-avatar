# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Bounded, history-free greeting preparation shared by scheduling and previews.

Scripted greetings are chosen here; an AI greeting is the LLM layer's request
(``src.llm.greeting``, ADR 0027).
"""
from __future__ import annotations

from dataclasses import asdict
import math
import random

from src.llm.greeting import GreetingGenerationError, generate_greeting
from src.utils.graphemes import visible_length

__all__ = ["GreetingError", "prepare_greeting", "validate_content", "validate_interval", "visible_length"]


class GreetingError(ValueError):
    pass


def validate_content(value: dict | None, *, required: bool = False) -> dict:
    defaults = dict(mode="scripts", scripts=[], scripts_en=[], prompt="", min_chars=20, max_chars=60)
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - set(defaults):
        raise GreetingError("招呼設定格式不正確")
    result = {**defaults, **value}
    if result["mode"] not in {"scripts", "ai"}:
        raise GreetingError("請選擇預寫文案或 AI 生成")
    for key in ("min_chars", "max_chars"):
        if type(result[key]) is not int or result[key] <= 0:
            raise GreetingError("招呼字數上下限須為正整數")
    if result["min_chars"] > result["max_chars"]:
        raise GreetingError("最少字數不可大於最多字數")
    scripts = result["scripts"]
    english = result["scripts_en"]
    if not isinstance(english, list) or len(english) > 100 or any(not isinstance(s, str) or len(s) > 12000 for s in english):
        raise GreetingError("英文預寫文案最多 100 篇，每篇 12000 字元")
    result["scripts_en"] = [s.strip() for s in english]
    if not isinstance(scripts, list) or len(scripts) > 100:
        raise GreetingError("預寫文案最多 100 篇")
    if any(not isinstance(s, str) or len(s) > 12000 for s in scripts):
        raise GreetingError("每篇預寫文案最多 12000 字元")
    result["scripts"] = [s.strip() for s in scripts]
    if not isinstance(result["prompt"], str) or len(result["prompt"]) > 12000:
        raise GreetingError("招呼 Prompt 最多 12000 字元")
    result["prompt"] = result["prompt"].strip()
    if required:
        if result["mode"] == "scripts" and not any(result["scripts"] + result["scripts_en"]):
            raise GreetingError("請先為主數位人填寫至少一篇招呼文案並儲存套用")
        if result["mode"] == "ai" and not result["prompt"]:
            raise GreetingError("請先為主數位人填寫招呼 Prompt 並儲存套用")
    return result


def validate_interval(value) -> float:
    if type(value) not in {int, float} or not math.isfinite(value) or value <= 0:
        raise GreetingError("招呼間隔須為正數秒")
    return float(value)


async def prepare_greeting(config, *, previous: str = "", generate=None, timeout=15.) -> dict:
    settings = validate_content(asdict(config.greeting), required=True)
    if settings["mode"] == "scripts":
        locale = getattr(getattr(config, 'conversation', None), 'locale', config.llm.assistant_profile.output_locale)
        scripts = settings['scripts_en'] if locale == 'en-US' else settings['scripts']
        choices = list(dict.fromkeys(s for s in scripts if s))
        if not choices:
            raise GreetingError('目前語系尚無預寫招呼文案，已略過本次')
        text = random.choice([s for s in choices if s != previous] or choices)
    else:
        try:
            text = await generate_greeting(config, settings["prompt"], min_chars=settings["min_chars"],
                                           max_chars=settings["max_chars"], generate=generate,
                                           timeout=timeout)
        except GreetingGenerationError as exc:
            raise GreetingError(str(exc)) from exc
    length = visible_length(text)
    return dict(text=text, length=length,
                in_range=settings["min_chars"] <= length <= settings["max_chars"])
