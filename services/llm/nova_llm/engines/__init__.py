# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""LLM 引擎實現集中入口"""

from nova_llm.base import BaseLLM
from .fake import FakeLLM
from .openai import OpenAILLM

DEFAULT_ENGINE = "openai-compatible"
# ``fake`` is selectable through ``llm.engine`` only; it is not an endpoint.
ENGINES: dict[str, type[BaseLLM]] = {DEFAULT_ENGINE: OpenAILLM, "fake": FakeLLM}

__all__ = ["BaseLLM", "DEFAULT_ENGINE", "ENGINES", "FakeLLM", "OpenAILLM"]
