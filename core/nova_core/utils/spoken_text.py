# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Spoken text shared by the core and the LLM layer."""
from __future__ import annotations


def join_spoken_fragments(fragments) -> str:
    """Keep Latin sentence spacing when individually trimmed speech is committed."""
    result = ''
    for text in fragments:
        if (result and text and result[-1] in '.!?,;:'
                and text[0].isascii() and text[0].isalnum()):
            result += ' '
        result += text
    return result
