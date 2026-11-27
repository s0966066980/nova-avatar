# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""In-process adapter that presents a recognizer engine as the ``SttService`` contract."""
from __future__ import annotations

from nova_contracts.stt import TranscribeResult

from src.asr.base import BaseASR


class SttAdapter:
    def __init__(self, engine: BaseASR) -> None:
        self._engine = engine

    def prewarm(self) -> None:
        self._engine.prewarm()

    def set_language(self, language: str) -> None:
        self._engine.set_language(language)

    def transcribe(self, audio: bytes, *, language: str | None = None) -> TranscribeResult:
        raw = self._engine.transcribe(audio, language=language) or {}
        confidence = raw.get("confidence", raw.get("avg_confidence"))
        return TranscribeResult(
            text=str(raw.get("text", "")).strip(),
            language=raw.get("language"),
            confidence=None if confidence is None else float(confidence),
        )
