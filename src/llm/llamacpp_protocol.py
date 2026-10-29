# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Thinking control for llama.cpp: LFM 2.5 needs a bounded envelope, others run without.

Reply syntax and policy are shared across models in reply_contract and prompts.
"""
from pathlib import Path


LFM_REASONING_BUDGET = 64


def is_lfm25_reasoning(model: str) -> bool:
    # Version dots belong to the model name; Path.stem would strip '.6B-...'
    # when the console stores a name without the .gguf suffix.
    name = Path(str(model)).name.lower().removesuffix('.gguf')
    return name == 'lfm2.5-2.6b' or name.startswith('lfm2.5-2.6b-')


def thinking_request_fields(model: str) -> dict:
    """Per-request chat-template switch for llama-server.

    Every model except LFM 2.5 answers without thinking. Asking for it in the
    request keeps thinking off even on an externally started server that was
    not launched with ``--reasoning off``; the Gemma 4 and Qwen 3.5 templates
    both read ``enable_thinking``.
    """
    if is_lfm25_reasoning(model):
        return {}
    return {'chat_template_kwargs': {'enable_thinking': False}}
