# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Reply modes. A single answer generation chooses the mode itself (ADR-0012)."""

from __future__ import annotations

from enum import Enum


class ReplyMode(str, Enum):
    """Response mode for assistant replies."""

    SIMPLE = "simple"
    BOARD = "board"
    AUTO = "auto"  # The single answer generation chooses the mode.
