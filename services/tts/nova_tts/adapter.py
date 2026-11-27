# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The TTS layer's entry point: ``TtsService`` and ``TtsRuntime`` served in-process.

The core reaches the TTS layer only through this module and ``config_section``;
everything else under ``nova_tts`` is internal (import-linter contract
``tts-internals-private``, ADR 0027).

The real-time path is unchanged by the split: a ``SpeechChannel`` is the
session's engine itself behind a thin wrapper, so every 20 ms frame still goes
from the engine's own thread straight to the core's ``AudioSink`` (ADR 0007).
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any, Optional

import numpy as np

from nova_contracts import CONTRACT_VERSION
from nova_contracts.common import ServiceHealth
from nova_contracts.tts import (
    MAX_VOICE_UPLOAD_BYTES,
    AudioSink,
    LibraryVoice,
    SpeechChannel,
    SynthesisRequest,
    TtsCatalog,
    TtsEngineSettings,
    TtsError,
    TtsModel,
    TtsVoice,
    VoiceList,
    VoiceModelInfo,
    VoiceModelPreview,
    VoicePreparation,
    VoiceRef,
    VoiceServerStatus,
    VoiceUpload,
    strip_visual_markup,
)
from nova_tts import cosyvoice_runtime, voice_library
from nova_tts.base import BaseTTS
from nova_tts.engines import edge
from nova_tts.factory import create_tts_engine
from nova_tts.training.service import InProcessVoiceTraining
from nova_tts.voice_models import VoiceModelNotFound, delete_voice_model, list_voice_models
from nova_tts.voice_preview import PreviewError, synthesize_preview
from nova_core.utils.logging import logger

SAMPLE_RATE = 16000
# A voice-model preview gives up after this long (the console waits as long).
PREVIEW_TIMEOUT_SECONDS = 60.0
_PCM_CHUNK_BYTES = 32 * 1024

EngineFactory = Callable[[str, Any, AudioSink], BaseTTS]


def _engine_config(voice: TtsVoice, settings: TtsEngineSettings) -> SimpleNamespace:
    """The configuration object the engines read (``config.tts`` / ``audio`` / ``matcha``)."""
    return SimpleNamespace(
        tts=SimpleNamespace(
            type=voice.engine,
            ref_file=voice.voice,
            ref_text=None,
            tts_server=voice.server,
            model=voice.model,
            edge_persistent_worker=voice.edge_persistent_worker,
            edge_prefetch=voice.edge_prefetch,
            edge_connection_reuse=voice.edge_connection_reuse,
        ),
        audio=SimpleNamespace(fps=settings.frames_per_second),
        matcha=SimpleNamespace(num_threads=settings.matcha_threads),
    )


class _EngineChannel:
    """One session's engine as a ``SpeechChannel``; frames never pass through here."""

    def __init__(self, engine: BaseTTS, voice: TtsVoice, settings: Callable[[], TtsEngineSettings]) -> None:
        self._engine = engine
        self._voice = voice
        self._settings = settings

    @property
    def voice(self) -> TtsVoice:
        return self._voice

    def set_voice(self, voice: TtsVoice) -> None:
        # Engines read their configuration per fragment; Matcha keeps the voice
        # model it loaded when the channel opened, as before.
        self._voice = voice
        self._engine.config = _engine_config(voice, self._settings())

    def speak(self, text: str, eventpoint: dict) -> None:
        self._engine.put_msg_txt(text, eventpoint)

    def flush(self) -> None:
        self._engine.flush_talk()

    def has_pending_work(self) -> bool:
        return self._engine.has_pending_work()

    def run(self, quit_event: Any) -> None:
        self._engine.render(quit_event)


class _CollectingSink:
    """An ``AudioSink`` that keeps up to ``limit`` samples of one synthesis."""

    def __init__(self, limit: Optional[int]) -> None:
        self.frames: list[np.ndarray] = []
        self._limit = limit
        self._samples = 0
        self.failure = ""

    def put_audio_frame(self, samples: np.ndarray, eventpoint: dict) -> bool:
        if self._limit is None or self._samples < self._limit:
            frame = np.asarray(samples, dtype=np.float32)
            self.frames.append(frame)
            self._samples += frame.size
        return True

    def accepts_media(self, eventpoint: dict, stage: str) -> bool:
        return True

    def fragment_playback_committed(self, eventpoint: dict) -> bool:
        return False

    def fragment_playback_ended(self, eventpoint: dict) -> bool:
        return True

    def notify_fragment_synthesis_failed(self, eventpoint: dict, reason: str) -> None:
        self.failure = reason

    def observe_tts_onset_preroll_ms(self, milliseconds: float) -> None:
        pass

    def observe_tts_retry(self, *, after_commit: bool) -> None:
        pass

    def mark_stage_end(self, stage: str) -> None:
        pass

    def pcm(self) -> bytes:
        if not self.frames:
            return b""
        samples = np.concatenate(self.frames)
        if self._limit is not None:
            samples = samples[: self._limit]
        return (np.clip(samples, -1.0, 1.0) * 32767.0).round().astype("<i2").tobytes()


def _library_error(exc: voice_library.VoiceLibraryError) -> TtsError:
    return TtsError(exc.message, status=exc.status)


class InProcessTtsService(InProcessVoiceTraining):
    """The TTS layer in the core's process: one instance per server."""

    def __init__(
        self,
        settings: TtsEngineSettings,
        *,
        create_engine: EngineFactory = create_tts_engine,
        **training: Any,
    ) -> None:
        self._settings = settings
        self._create_engine = create_engine
        InProcessVoiceTraining.__init__(self, settings=lambda: self._settings, **training)

    # ------------------------------------------------------------ service

    def health(self) -> ServiceHealth:
        return ServiceHealth(contract_version=CONTRACT_VERSION, engine="in-process", ready=True)

    def apply_engine(self, settings: TtsEngineSettings) -> TtsEngineSettings:
        self._settings = settings
        return settings

    def catalog(self) -> TtsCatalog:
        return TtsCatalog(
            voices=tuple(LibraryVoice.model_validate(item) for item in voice_library.list_voices()),
            models=tuple(TtsModel.model_validate(item) for item in cosyvoice_runtime.local_models()),
            voice_models=tuple(
                VoiceModelInfo(id=model.id, name=model.name, usage=model.usage,
                               languages=tuple(model.languages), source=model.source)
                for model in list_voice_models()
            ),
        )

    def server_status(self, voice: TtsVoice) -> VoiceServerStatus:
        host, port = cosyvoice_runtime.parse_server_url(voice.server)
        return VoiceServerStatus(ready=cosyvoice_runtime.server_ready(voice.server, voice.model),
                                 url=cosyvoice_runtime.server_url(host, port))

    def prepare_voice(self, request: VoicePreparation) -> TtsVoice:
        voice = request.voice
        if voice.engine == "edgetts":
            timeout = request.timeout_seconds or edge.EDGE_WARMUP_TIMEOUT_SECONDS
            if not edge.prewarm_edge_tts(voice.voice, decode_pcm=True,
                                         keep_connection=voice.edge_connection_reuse,
                                         timeout_seconds=timeout):
                raise TtsError("Edge TTS 暫時無法連線", status=503)
            return voice
        if voice.engine == "breezyvoice":
            host, port = cosyvoice_runtime.parse_server_url(voice.server)
            try:
                url = cosyvoice_runtime.ensure_server(model_dir=voice.model, host=host, port=port)
            except FileNotFoundError as exc:
                raise TtsError(str(exc)) from exc
            except (RuntimeError, TimeoutError, OSError) as exc:
                raise TtsError(str(exc), status=503) from exc
            return voice.model_copy(update={"server": url})
        return voice

    def synthesize(self, request: SynthesisRequest) -> Iterator[bytes]:
        # In-process this is the bounded, non-real-time path (previews): the
        # engine runs to the end of the fragment here, then the PCM is returned.
        limit = None if request.max_seconds is None else int(request.max_seconds * SAMPLE_RATE)
        sink = _CollectingSink(limit)
        text = strip_visual_markup(request.fragment.text)
        try:
            engine = self._create_engine(request.voice.engine, _engine_config(request.voice, self._settings), sink)
            engine.txt_to_audio((text, {"synthesis": request.fragment.fragment_id,
                                        "estimated_seconds": request.fragment.estimated_seconds}))
        except Exception as exc:
            raise TtsError(str(exc), status=502) from exc
        pcm = sink.pcm()
        return iter([pcm[start:start + _PCM_CHUNK_BYTES] for start in range(0, len(pcm), _PCM_CHUNK_BYTES)])

    def list_voices(self) -> VoiceList:
        return VoiceList(voices=tuple(LibraryVoice.model_validate(item) for item in voice_library.list_voices()))

    def voice_audio(self, ref: VoiceRef) -> bytes:
        try:
            return voice_library.voice_path(ref.voice_id).read_bytes()
        except voice_library.VoiceLibraryError as exc:
            raise _library_error(exc) from None

    def add_voice(self, audio: bytes, upload: VoiceUpload) -> LibraryVoice:
        if len(audio) > MAX_VOICE_UPLOAD_BYTES:
            raise TtsError(f"參考音訊不可超過 {MAX_VOICE_UPLOAD_BYTES / 1024 / 1024:g} MB", status=413)
        root = voice_library.voices_root()
        temporary = root / f".upload-{uuid.uuid4().hex}"
        try:
            root.mkdir(parents=True, exist_ok=True)
            temporary.write_bytes(audio)
            return LibraryVoice.model_validate(voice_library.add_voice(temporary, upload.name, upload.transcript))
        except voice_library.VoiceLibraryError as exc:
            raise _library_error(exc) from None
        finally:
            temporary.unlink(missing_ok=True)

    def delete_voice(self, ref: VoiceRef) -> None:
        try:
            voice_library.delete_voice(ref.voice_id)
        except voice_library.VoiceLibraryError as exc:
            raise _library_error(exc) from None

    def delete_voice_model(self, ref: VoiceRef) -> None:
        if self.writes_voice_model(ref.voice_id):
            raise TtsError("這個聲線模型正在訓練中，請先取消訓練", status=409)
        try:
            delete_voice_model(ref.voice_id)
        except VoiceModelNotFound:
            raise TtsError("找不到這個聲線模型", status=404) from None

    def preview_voice_model(self, request: VoiceModelPreview) -> bytes:
        deadline = time.monotonic() + PREVIEW_TIMEOUT_SECONDS
        try:
            return synthesize_preview(request.voice_id, request.sentence,
                                      num_threads=self._settings.matcha_threads,
                                      keep_going=lambda: time.monotonic() < deadline)
        except PreviewError as exc:
            raise TtsError(exc.message, status=exc.status) from exc

    # ------------------------------------------------------------ runtime

    def open_channel(self, voice: TtsVoice, sink: AudioSink) -> SpeechChannel:
        engine = self._create_engine(voice.engine, _engine_config(voice, self._settings), sink)
        return _EngineChannel(engine, voice, lambda: self._settings)

    def start(self) -> None:
        self._start_training()

    def close(self, *, force: bool = False) -> None:
        if force:
            cosyvoice_runtime.shutdown_cosyvoice_server()
            return
        self._stop_training()
        try:
            edge.shutdown_edge_tts()
        except Exception:
            logger.exception("關閉 Edge TTS 連線失敗")
        cosyvoice_runtime.shutdown_cosyvoice_server()


def create_tts_service(settings: TtsEngineSettings) -> InProcessTtsService:
    """The process's TTS service and runtime; the core creates one at startup."""
    return InProcessTtsService(settings)


__all__ = ["InProcessTtsService", "create_tts_service"]
