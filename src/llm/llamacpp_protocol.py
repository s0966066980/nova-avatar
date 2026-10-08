# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""LFM 2.5 launcher capability: its template requires a bounded thinking envelope.

Reply syntax and policy are shared across models in reply_contract and prompts.
"""
from pathlib import Path


LFM_REASONING_BUDGET = 64


def is_lfm25_reasoning(model: str) -> bool:
    # Version dots belong to the model name; Path.stem would strip '.6B-...'
    # when the console stores a name without the .gguf suffix.
    name = Path(str(model)).name.lower().removesuffix('.gguf')
    return name == 'lfm2.5-2.6b' or name.startswith('lfm2.5-2.6b-')
