# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Length of text as a visitor sees it."""
from __future__ import annotations

import regex


def visible_length(text: str) -> int:
    """Count grapheme clusters, skipping whitespace (punctuation counts)."""
    return sum(not regex.fullmatch(r"\p{White_Space}+", part) for part in regex.findall(r"\X", text))
