# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Speech-to-text: audio in, text out. Transport when split: ``POST`` audio, JSON back."""
from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class TranscribeResult(BaseModel):
    text: str
    language: str | None = None
    confidence: float | None = None


class SttService(Protocol):
    def prewarm(self) -> None:
        """Load the recognizer and run one inference."""

    def set_language(self, language: str) -> None: ...

    def transcribe(self, audio: bytes, *, language: str | None = None) -> TranscribeResult:
        """Recognize one utterance; ``language="auto"`` detects it."""
