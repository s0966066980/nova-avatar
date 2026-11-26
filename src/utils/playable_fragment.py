# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""A reply fragment that is ready for TTS and playback.

The core cuts fragments and the TTS layer synthesizes them, so the type lives
in this shared leaf until ticket 07 moves it into ``contracts/``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class FragmentEnvelope(Protocol):
    """The turn identity a fragment carries (the core's TurnEnvelope)."""

    @property
    def turn_id(self) -> str: ...

    @property
    def generation(self) -> int: ...

    @property
    def sequence(self) -> int: ...


@dataclass(frozen=True)
class PlayableFragment:
    envelope: FragmentEnvelope
    text: str
    estimated_seconds: float

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("fragment text cannot be empty")
        if self.estimated_seconds < 0:
            raise ValueError("estimated duration cannot be negative")

    @property
    def fragment_id(self) -> str:
        return f"{self.envelope.turn_id}:{self.envelope.sequence}"
