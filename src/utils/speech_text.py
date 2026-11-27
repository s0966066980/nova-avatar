# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Plain-text cleanup shared by the core, the TTS layer and the renderer."""
from __future__ import annotations

import re

_EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0000FE0F"
    "\U0000200D"
    "]+"
)


def sanitize_speech_text(text: str) -> str:
    """Remove visual Markdown/emoji that speech engines may pronounce aloud."""
    value = str(text or "")
    value = re.sub(r"!\[([^]]*)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"(?m)^\s{0,3}(?:#{1,6}|>|[-+*])\s+", "", value)
    value = re.sub(r"```(?:\w+)?|`", "", value)
    value = re.sub(r"[*_~]+", "", value)
    value = _EMOJI_RE.sub("", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r" *\n+ *", "，", value)
    return value.strip(" ，")
