# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Automatic transcripts for a training corpus, produced in a background thread.

``TranscriptionJobs`` runs one job at a time on a worker thread, so a request
never waits for a model (CODING_STANDARDS 3): ``start`` returns at once, the
console polls ``status`` and may ``cancel``. The worker builds its transcriber
from an injected factory, so tests use a fake and the server uses
``FasterWhisperTranscriber``; the transcriber is closed when the job ends for
any reason, which releases the model (and its GPU memory).

Only lines that have no transcript and are not excluded are transcribed, and a
result is stored with ``set_text(only_if_empty=True)``: text the administrator
typed while the job ran is never overwritten. Results are stored as ``pending``
lines, so they still go through the review table.

``FasterWhisperTranscriber`` loads a faster-whisper model that is already in the
local cache (never downloading), detects the language itself and converts the
text to Traditional Chinese (Taiwan wording) with OpenCC ``s2twp``.

The device is decided once, when a job starts, by the GPU guard (``choose_device``,
``gpu_guard.choose_transcription_device``): a connected stage or too little free VRAM
means the CPU (int8) with a reason, never a refusal and never a silent switch. The
status carries ``device`` and ``fallback_reason``; a running job does not migrate when
the stage connects later. If the GPU still cannot run the model, for example because
the CUDA libraries are not on the library path, the transcriber falls back to the CPU
once and the status then says so.
"""

from __future__ import annotations

import gc
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from src.tts.training.corpus import REVIEW_EXCLUDED, CorpusError, CorpusStore, Line
from src.tts.training.gpu_guard import DEVICE_CPU, DEVICE_CUDA, DeviceChoice
from src.utils.logging import logger

# faster-whisper models that may be requested; they must already be in the cache.
ALLOWED_MODELS = ("small", "medium", "large-v3")
DEFAULT_MODEL = "medium"

STATE_IDLE = "idle"
STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_CANCELLED = "cancelled"
STATE_FAILED = "failed"


class Transcriber(Protocol):
    def transcribe(self, path: Path) -> str: ...

    def close(self) -> None: ...


TranscriberFactory = Callable[[str, str], Transcriber]  # (model size, device)
DeviceChooser = Callable[[], DeviceChoice]
REASON_GPU_FAILED = "GPU 執行失敗，已改用 CPU"


@dataclass(frozen=True)
class FailedLine:
    line_id: str
    message: str


@dataclass(frozen=True)
class TranscriptionStatus:
    state: str
    slug: str | None = None
    model: str | None = None
    total: int = 0
    done: int = 0
    skipped: int = 0
    failed: tuple[FailedLine, ...] = ()
    message: str = ""
    cancel_requested: bool = False
    device: str | None = None  # "cuda" or "cpu" once a job has started
    fallback_reason: str | None = None  # why it is "cpu" rather than "cuda"


IDLE = TranscriptionStatus(STATE_IDLE)


class TranscriptionJobs:
    """The one transcription job of a store, run on its own worker thread."""

    def __init__(self, store: CorpusStore, factory: TranscriberFactory, choose_device: DeviceChooser) -> None:
        self.store = store
        self.factory = factory
        self.choose_device = choose_device
        self._lock = threading.Lock()
        self._status = IDLE
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------ public

    def start(
        self, slug: str, line_ids: list[str] | None = None, model: str = DEFAULT_MODEL
    ) -> TranscriptionStatus:
        """Start transcribing the corpus's lines that lack a transcript."""
        if model not in ALLOWED_MODELS:
            raise CorpusError(f"不支援的語音辨識模型，可用：{'、'.join(ALLOWED_MODELS)}")
        corpus = self.store.get(slug)
        if line_ids is not None:
            known = {line.id for line in corpus.lines}
            missing = [item for item in line_ids if item not in known]
            if missing:
                raise CorpusError("找不到指定的句子", status=404)
        wanted = set(line_ids) if line_ids is not None else None
        targets = [
            line
            for line in corpus.lines
            if (wanted is None or line.id in wanted) and not line.text and line.review != REVIEW_EXCLUDED
        ]
        if not targets:
            raise CorpusError("沒有需要自動產生逐字稿的音檔", status=409)
        # Decided once, outside the lock because it may run nvidia-smi; never changed mid-job.
        choice = self.choose_device()
        with self._lock:
            if self._status.state == STATE_RUNNING:
                raise CorpusError("已有一項逐字稿作業進行中，請等它完成或取消", status=409)
            self._cancel.clear()
            self._status = TranscriptionStatus(
                STATE_RUNNING, slug, model, total=len(targets),
                device=choice.device, fallback_reason=choice.fallback_reason,
            )
            thread = threading.Thread(
                target=self._run, args=(slug, targets, model, choice.device), name="tts-corpus-transcription", daemon=True
            )
            self._thread = thread
            started = self._status
        thread.start()
        return started

    def status(self, slug: str | None = None) -> TranscriptionStatus:
        """The current or last job; ``idle`` when it belongs to another corpus."""
        with self._lock:
            current = self._status
        return current if slug is None or current.slug == slug else IDLE

    def cancel(self, slug: str) -> TranscriptionStatus:
        """Ask the running job to stop after the file it is on."""
        with self._lock:
            if self._status.state != STATE_RUNNING or self._status.slug != slug:
                raise CorpusError("目前沒有進行中的逐字稿作業", status=409)
            self._cancel.set()
            self._status = replace(self._status, cancel_requested=True)
            return self._status

    def stop(self, timeout: float = 10.0) -> None:
        """Cancel whatever is running and wait for the worker; used at server shutdown."""
        self._cancel.set()
        self.wait(timeout)

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the worker has finished; for tests and shutdown."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
            return not thread.is_alive()
        return True

    # ------------------------------------------------------------ worker

    def _update(self, **changes: Any) -> None:
        with self._lock:
            self._status = replace(self._status, **changes)

    def _run(self, slug: str, targets: list[Line], model: str, device: str) -> None:
        transcriber: Transcriber | None = None
        done = skipped = 0
        failed: list[FailedLine] = []
        final = STATE_DONE
        message = ""
        try:
            transcriber = self.factory(model, device)
            for line in targets:
                if self._cancel.is_set():
                    final = STATE_CANCELLED
                    break
                try:
                    text = transcriber.transcribe(self.store.audio_path(slug, line.id)).strip()
                    if not text:
                        failed.append(FailedLine(line.id, "沒有辨識到文字"))
                    elif self.store.set_text(slug, line.id, text, only_if_empty=True).text != text:
                        skipped += 1
                    else:
                        done += 1
                except Exception as exc:
                    logger.warning("Transcribing line %s of %s failed: %s", line.id, slug, exc)
                    failed.append(FailedLine(line.id, f"辨識失敗：{exc}"[:300]))
                self._update(done=done, skipped=skipped, failed=tuple(failed))
                # The adapter retries on the CPU when the GPU cannot run the model; say so.
                if device == DEVICE_CUDA and getattr(transcriber, "device", device) == DEVICE_CPU:
                    device = DEVICE_CPU
                    self._update(device=device, fallback_reason=REASON_GPU_FAILED)
        except Exception as exc:
            logger.exception("Transcription job for %s failed", slug)
            final = STATE_FAILED
            message = f"無法載入語音辨識模型，請確認 {model} 已下載到本機快取：{exc}"[:300]
        finally:
            if transcriber is not None:
                try:
                    transcriber.close()
                except Exception:
                    logger.exception("Releasing the transcription model failed")
            self._update(
                state=final, done=done, skipped=skipped, failed=tuple(failed), message=message
            )


# ------------------------------------------------------------------ faster-whisper


def cuda_available() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def _load_whisper(size: str, device: str):
    """A cached faster-whisper model; ``local_files_only`` forbids any download."""
    from faster_whisper import WhisperModel

    compute_type = "float16" if device == "cuda" else "int8"
    return WhisperModel(size, device=device, compute_type=compute_type, local_files_only=True)


class FasterWhisperTranscriber:
    """Transcribe audio files with faster-whisper into Traditional Chinese text."""

    def __init__(
        self,
        model_size: str,
        device: str | None = None,
        *,
        model_factory: Callable[[str, str], Any] = _load_whisper,
        converter: Any = None,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self._model_factory = model_factory
        self._converter = converter
        self._model: Any = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _load(self, device: str) -> Any:
        self.device = device
        logger.info("Loading faster-whisper %s on %s for corpus transcription", self.model_size, device)
        self._model = self._model_factory(self.model_size, device)
        return self._model

    def _convert(self, text: str) -> str:
        if self._converter is None:
            from opencc import OpenCC

            self._converter = OpenCC("s2twp")
        return self._converter.convert(text)

    def _recognize(self, model: Any, path: Path) -> str:
        # language=None lets faster-whisper detect Chinese or English per file.
        segments, _info = model.transcribe(str(path), language=None, beam_size=3, vad_filter=False)
        return "".join(segment.text for segment in segments).strip()

    def transcribe(self, path: Path) -> str:
        if self._model is None:
            self._load(self.device or ("cuda" if cuda_available() else "cpu"))
        try:
            text = self._recognize(self._model, path)
        except Exception as exc:
            if self.device != "cuda":
                raise
            # CUDA often fails only when the first batch runs (missing libraries).
            logger.warning("faster-whisper failed on the GPU (%s); retrying on the CPU", exc)
            self.close()
            text = self._recognize(self._load("cpu"), path)
        return self._convert(text)

    def close(self) -> None:
        """Drop the model so its memory is freed."""
        if self._model is None:
            return
        # CTranslate2 frees the weights, on the GPU too, when the model is collected.
        self._model = None
        gc.collect()


def default_factory(model: str, device: str) -> Transcriber:
    """The transcriber the server uses: a cached faster-whisper model on the decided device."""
    return FasterWhisperTranscriber(model, device)
