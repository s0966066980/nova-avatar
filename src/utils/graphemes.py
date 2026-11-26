# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Visible length as a visitor reads it: user-perceived characters, not code points."""
from __future__ import annotations

import regex


def visible_length(text: str) -> int:
    """Grapheme clusters that are not whitespace, so punctuation counts and spaces do not."""
    return sum(not regex.fullmatch(r"\p{White_Space}+", part) for part in regex.findall(r"\X", text))
