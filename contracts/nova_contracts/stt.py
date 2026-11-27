# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Speech-to-text (STT) layer contract.

Loopback shape (spec decision 7): ``POST /transcribe`` takes the audio as the
request body and returns a ``Transcription`` as JSON.
"""
from __future__ import annotations

from typing import Literal, Optional, Protocol, runtime_checkable

from nova_contracts.common import ContractModel, ServiceHealth
from nova_contracts.http import (
    BinaryBody,
    HttpApi,
    HttpOperation,
    JsonBody,
    engine_operation,
    health_operation,
)

# Speech turns detect Chinese or English per turn; ``/asr`` uploads may fix one.
SttLanguage = Literal["zh", "en", "auto"]
SttDevice = Literal["auto", "cpu", "cuda"]


class SttEngineSettings(ContractModel):
    """The recognizer the service runs (``PUT /engine``).

    ``model_size`` is a catalog name the core validated, never a path.
    """

    engine: str
    model_size: str
    device: SttDevice = "auto"


class SttPrepareRequest(ContractModel):
    """Load the recognizer; with ``warm`` also run one silent inference."""

    warm: bool = True


class TranscriptionOptions(ContractModel):
    """Per-request options; the recognizer itself is shared and unchanged."""

    language: SttLanguage


class TranscriptionSegment(ContractModel):
    start: float
    end: float
    text: str


class Transcription(ContractModel):
    """What was heard in one utterance."""

    text: str
    # The detected language for ``auto``; otherwise the requested one.
    language: Optional[str] = None
    language_probability: Optional[float] = None
    # 0..1 from the mean token log-probability, when the engine reports it.
    confidence: Optional[float] = None
    segments: tuple[TranscriptionSegment, ...] = ()


@runtime_checkable
class SttService(Protocol):
    """The STT layer as the core sees it; each method is one HTTP operation."""

    def health(self) -> ServiceHealth:
        """``GET /health``."""
        ...

    def apply_engine(self, settings: SttEngineSettings) -> SttEngineSettings:
        """``PUT /engine``: load the new recognizer, then switch to it.

        Raises ``ServiceError`` and keeps the current recognizer when the new
        one cannot be loaded.
        """
        ...

    def prepare(self, request: SttPrepareRequest) -> None:
        """``POST /prepare``: make the first ``transcribe`` fast. Raises on failure."""
        ...

    def transcribe(self, audio: bytes, options: TranscriptionOptions) -> Transcription:
        """``POST /transcribe``: recognize one encoded utterance (WAV, FLAC, MP3 ...)."""
        ...


HTTP_API = HttpApi(
    title="Nova Avatar STT service",
    description="Loopback speech-to-text. The core cancels a request by closing its connection.",
    service=SttService,
    operations=(
        health_operation(),
        engine_operation(SttEngineSettings),
        HttpOperation("POST", "/prepare", "prepare", "Load, and optionally warm, the recognizer",
                      request=JsonBody(SttPrepareRequest)),
        HttpOperation("POST", "/transcribe", "transcribe", "Recognize one utterance",
                      query=TranscriptionOptions,
                      request=BinaryBody(("audio/wav", "application/octet-stream"),
                                         "One encoded utterance; the core sends 16 kHz WAV"),
                      response=JsonBody(Transcription)),
    ),
)


__all__ = [
    "HTTP_API",
    "SttDevice",
    "SttEngineSettings",
    "SttLanguage",
    "SttPrepareRequest",
    "SttService",
    "Transcription",
    "TranscriptionOptions",
    "TranscriptionSegment",
]
