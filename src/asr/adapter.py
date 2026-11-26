# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The STT layer's entry point: ``SttService`` served in-process (ADR 0027).

The core reaches the STT layer only through this module and
``config_section``; everything else under ``src.asr`` is internal
(import-linter contract ``stt-internals-private``).
"""
from __future__ import annotations

from threading import RLock
from typing import Callable, Optional

from nova_contracts import CONTRACT_VERSION
from nova_contracts.common import ServiceError, ServiceHealth
from nova_contracts.stt import (
    SttEngineSettings,
    SttPrepareRequest,
    SttService,
    Transcription,
    TranscriptionOptions,
)
from src.asr.base import BaseASR
from src.asr.factory import create_asr_engine


class InProcessSttService:
    """One shared recognizer per process, switched only after its successor loads."""

    def __init__(
        self,
        settings: SttEngineSettings,
        *,
        create_engine: Callable[[SttEngineSettings], BaseASR] = create_asr_engine,
    ) -> None:
        self._settings = settings
        self._create_engine = create_engine
        self._engine: Optional[BaseASR] = None
        self._loaded = False
        # Voice sessions prepare from executor threads; serialize the
        # check-and-create so they cannot each load a GPU model.
        self._lock = RLock()

    def health(self) -> ServiceHealth:
        with self._lock:
            return ServiceHealth(
                contract_version=CONTRACT_VERSION,
                engine=self._settings.engine,
                ready=self._loaded,
            )

    def apply_engine(self, settings: SttEngineSettings) -> SttEngineSettings:
        # Loading may take seconds; the current recognizer keeps serving meanwhile.
        candidate = self._create_engine(settings)
        try:
            candidate.ensure_ready()
        except Exception as exc:
            raise ServiceError(str(exc)) from exc
        with self._lock:
            self._settings, self._engine, self._loaded = settings, candidate, True
        return settings

    def prepare(self, request: SttPrepareRequest) -> None:
        engine = self._loaded_engine()
        if request.warm:
            engine.prewarm()

    def transcribe(self, audio: bytes, options: TranscriptionOptions) -> Transcription:
        result = self._loaded_engine().transcribe(audio, language=options.language)
        return Transcription.model_validate(result)

    def _loaded_engine(self) -> BaseASR:
        with self._lock:
            if self._engine is None:
                self._engine = self._create_engine(self._settings)
            engine = self._engine
        # Engines load once under their own lock; later calls return at once.
        engine.ensure_ready()
        with self._lock:
            if self._engine is engine:
                self._loaded = True
        return engine


def create_stt_service(settings: SttEngineSettings) -> SttService:
    """The process's STT service; the core creates one at startup and shares it."""
    return InProcessSttService(settings)


__all__ = ["InProcessSttService", "create_stt_service"]
