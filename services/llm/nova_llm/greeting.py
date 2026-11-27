# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""AI-written idle greetings: one history-free request to the role's model.

The core owns the schedule, the pre-written scripts and the settings; it hands
this layer the console config and the validated greeting settings
(``prompt``, ``min_chars``, ``max_chars``) and gets plain text back.
"""
from __future__ import annotations

import asyncio
import re

from openai import AsyncOpenAI

from nova_llm.text_normalizer import normalize_assistant_identity, normalize_output_text
from nova_core.utils.visible_text import visible_length


class GreetingGenerationError(ValueError):
    """The model produced no usable greeting; the message is safe to show."""


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


async def _generate(config, messages, *, client_factory=None) -> str:
    extra = dict(config.llm.extra_body or {})
    if config.llm.provider == "llamacpp":
        for key in ("reasoning_effort", "think", "keep_alive", "options"):
            extra.pop(key, None)
    # config.llm URL and key were set together from one allowlisted endpoint.
    async with (client_factory or AsyncOpenAI)(api_key=config.llm.api_key or "nova-avatar-local",
                              base_url=config.llm.base_url, timeout=15., max_retries=0) as client:
        response = await client.chat.completions.create(
            model=config.llm.model, messages=messages, stream=False,
            max_tokens=max(128, min(8192, config.greeting.max_chars * 4)),
            extra_body=extra or None,
        )
        return response.choices[0].message.content or ""


async def generate_greeting(config, settings: dict, *, generate=None, timeout=15.) -> str:
    """One greeting of ``settings['min_chars']``..``max_chars`` visible characters.

    Retries once when the first reply is markup or the wrong length. Raises
    ``GreetingGenerationError`` for a bad reply, a timeout or a model failure.
    """
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
        raise GreetingGenerationError("AI 招呼格式或字數不合格，已略過本次")

    try:
        return await asyncio.wait_for(attempts(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise GreetingGenerationError("AI 招呼生成超過 15 秒，已略過本次") from exc
    except GreetingGenerationError:
        raise
    except Exception as exc:
        raise GreetingGenerationError("AI 招呼生成失敗，已略過本次") from exc
