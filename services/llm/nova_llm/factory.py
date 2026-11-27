# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""LLM 工廠類"""

from typing import Type

from .engines import BaseLLM, OpenAILLM

_ENGINE_MAP: dict[str, Type[BaseLLM]] = {
    "openai": OpenAILLM,
    "gpt": OpenAILLM,
    "dashscope": OpenAILLM,
    "qwen": OpenAILLM,
    "claude": OpenAILLM,
    "ollama": OpenAILLM,
    "vllm": OpenAILLM,
}


def create_llm_engine(llm_type: str = "openai", config=None, parent=None) -> BaseLLM:
    """根據型別建立 LLM 引擎"""
    engine_cls = _ENGINE_MAP.get(llm_type.lower())
    if engine_cls is None:
        raise ValueError(
            f"未知的 LLM 型別: {llm_type!r}\n"
            f"支援的型別: {', '.join(_ENGINE_MAP.keys())}"
        )
    return engine_cls(config, parent)
