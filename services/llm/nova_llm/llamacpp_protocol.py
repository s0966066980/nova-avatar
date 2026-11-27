# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Thinking control for llama.cpp: every supported model answers without thinking.

Reply syntax and policy are shared across models in reply_contract and prompts.
"""


def thinking_request_fields() -> dict:
    """Per-request chat-template switch for llama-server.

    Asking for it in the request keeps thinking off even on an externally
    started server that was not launched with ``--reasoning off``; the Gemma 4
    and Qwen 3.5 templates both read ``enable_thinking``.
    """
    return {'chat_template_kwargs': {'enable_thinking': False}}
