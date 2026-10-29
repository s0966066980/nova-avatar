# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Bounded, history-free greeting preparation shared by scheduling and previews."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
import math
import random
import re

import regex
from openai import AsyncOpenAI

from src.llm.text_normalizer import normalize_assistant_identity, normalize_output_text


class GreetingError(ValueError):
    pass


def visible_length(text: str) -> int:
    return sum(not regex.fullmatch(r"\p{White_Space}+", part) for part in regex.findall(r"\X", text))


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


def greeting_messages(config, settings: dict) -> list[dict]:
    identity = config.llm.assistant_profile
    system = "\n".join(filter(None, [
        f"你的名字是 {identity.assistant_name}。" if identity.assistant_name else "",
        identity.system_prompt, identity.restriction_prompt,
        f"輸出語系：{identity.output_locale}。",
        "禁止自稱：" + "、".join(identity.forbidden_self_names) if identity.forbidden_self_names else "",
        "產生一段對現場訪客的招呼或自我介紹。只輸出一段純文字，不要標題、清單、JSON、註解或工具呼叫。",
        f"文字必須為 {settings['min_chars']}～{settings['max_chars']} 個可見字元，包含標點、不計空白。",
    ]))
    return [{"role": "system", "content": system},
            {"role": "user", "content": settings["prompt"]}]


async def _generate(config, messages, *, client_factory=AsyncOpenAI) -> str:
    extra = dict(config.llm.extra_body or {})
    if config.llm.provider == "llamacpp":
        for key in ("reasoning_effort", "think", "keep_alive", "options"):
            extra.pop(key, None)
    async with client_factory(api_key=config.llm.api_key or "nova-avatar-local",
                              base_url=config.llm.base_url, timeout=15., max_retries=0) as client:
        response = await client.chat.completions.create(
            model=config.llm.model, messages=messages, stream=False,
            max_tokens=max(128, min(8192, config.greeting.max_chars * 4)),
            extra_body=extra or None,
        )
        return response.choices[0].message.content or ""


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
        generate = generate or _generate

        async def attempts():
            messages = greeting_messages(config, settings)
            for attempt in range(2):
                raw = await generate(config, messages)
                identity = config.llm.assistant_profile
                text = normalize_output_text(str(raw), locale=identity.output_locale,
                                             enabled=identity.enforce_output_locale)
                text = normalize_assistant_identity(text, assistant_name=identity.assistant_name,
                                                     forbidden_names=identity.forbidden_self_names)
                # Protocol/markup output must never be read aloud as a greeting.
                plain = not (re.search(r"```|^\s*[\[{]|^\s*(?:#{1,6}|[-*])\s|<tool", text, re.MULTILINE))
                text = " ".join(text.split()).strip()
                if plain and settings["min_chars"] <= visible_length(text) <= settings["max_chars"]:
                    return text
                if attempt == 0:
                    messages = greeting_messages(config, settings)
                    messages[-1]["content"] += "\n上次產生的格式或字數不合格，請重新產生一段純文字並嚴格遵守字數範圍。"
            raise GreetingError("AI 招呼格式或字數不合格，已略過本次")

        try:
            text = await asyncio.wait_for(attempts(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise GreetingError("AI 招呼生成超過 15 秒，已略過本次") from exc
        except GreetingError:
            raise
        except Exception as exc:
            raise GreetingError("AI 招呼生成失敗，已略過本次") from exc
    length = visible_length(text)
    return dict(text=text, length=length,
                in_range=settings["min_chars"] <= length <= settings["max_chars"])
