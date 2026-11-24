# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""A reply fragment that is ready for TTS and playback."""
from __future__ import annotations

from dataclasses import dataclass

from .turn import TurnEnvelope


@dataclass(frozen=True)
class PlayableFragment:
    envelope: TurnEnvelope
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
