# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
# Adapted from core/nova_core/server/tts_training_jobs.py on the jetson-orin branch.
# Modified by HongXian0903, 2026.

"""Training jobs (訓練工作): from a corpus to a voice model in the catalog.

One job at a time. A job is a worker thread that runs these stages in order:

1. ``environment``: the training venv, base weights and base assets are present;
2. ``synthesis`` (Edge test-teacher corpora only; needs the recorded MSA
   acknowledgement) or ``preparation`` (uploaded recordings: convert to 16 kHz);
3. ``quality``: ``audio_quality`` per line, then the Whisper similarity check on the CPU
   (``transcript_check.verify_with_asr`` through ``asr.SubprocessTranscriber``); lines
   that fail are excluded from the corpus, never silently kept, and the stage is never
   skipped;
4. ``training``: ``integrations/matcha-train/scripts/train_matcha.py`` in a child of the training venv;
5. ``export``: ``export_matcha_onnx.py`` in the same venv, a sherpa-onnx load check of
   the bundle in the application's interpreter on the CPU, then the atomic write into
   ``models/tts/<id>/`` (``bundle.install_voice_model``). Nothing here can be downloaded.

Whether a job may start is a list of named checks (``evaluate_preflight``) with a reason
each, evaluated before starting and again by the status route, so the console can show
them. These are the TTS layer's checks only: whether a stage is connected is core state,
so the core checks it before it asks this layer and puts that check in front of these
(spec decision 14). Cancelling sends SIGTERM to the running child, then SIGKILL after a grace period,
which releases the GPU; the corpus is kept, training progress is not. A job's log is kept
in memory (bounded, read by offset) and in ``<corpus>/jobs/<job id>/log.txt``; its state
is saved under ``<training root>/.jobs/`` so that a restart marks a job that was running as
failed and stops a training child that outlived the server.

Everything blocking (``nvidia-smi``, files, children) happens in worker threads or in
the route's ``asyncio.to_thread`` call (CODING_STANDARDS 3); the manager's lock is never
held across ``nvidia-smi`` or other slow IO, so status and cancel stay responsive.

Lifecycle: the server calls ``recover()`` once at startup (jobs that were running are
failed and their child processes, the training child or the Whisper child recorded in the
job state, are stopped with SIGTERM, then SIGKILL) and ``shutdown()`` when it stops (the
running job is cancelled and its child killed, so the GPU is freed). A training job
is refused while an automatic transcription runs: both want the same CPU and GPU.
"""

from __future__ import annotations

import collections
import json
import os
import re
import secrets
import shutil
import signal
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nova_tts.training import edge_teacher
from nova_tts.training.asr import DEFAULT_MODEL as DEFAULT_WHISPER_MODEL
from nova_tts.training.asr import (
    UTTERANCE_TIMEOUT_SECONDS,
    SubprocessTranscriber,
    TranscriberError,
)
from nova_tts.training.bundle import (
    BundleError,
    check_model_name,
    install_voice_model,
    new_model_id,
    source_description,
)
from nova_tts.training.corpus import (
    REASON_NO_CONFIRMED_LINES,
    REASON_PENDING_LINES,
    REASON_SOURCE_MISSING,
    REASON_UNRESOLVED_DIGITS,
    REVIEW_CONFIRMED,
    CorpusError,
    CorpusStore,
)
from nova_tts.training.edge_acknowledgement import MSA_CLAUSE, require_acknowledgement
from nova_tts.training.gpu_guard import (
    DEFAULT_MIN_FREE_VRAM_GB,
    FAIL,
    PASS,
    WARN,
    Check,
    free_vram_check,
)
from nova_tts.training.gpu_probe import VramReading, read_free_vram
from nova_tts.training.manifest import build_manifest
from nova_tts.training.preparation import PreparationReport, check_quality, convert_uploads
from nova_tts.training.processes import DEFAULT_GRACE_SECONDS, Spawn, run_process, spawn_process
from nova_tts.training.sentences import PRESETS, estimate_seconds, review_text_list, select_preset
from nova_tts.training.transcript_check import DEFAULT_MIN_SIMILARITY, Transcriber, verify_with_asr
from nova_tts.training.usage import SOURCE_EDGE_TEST_TEACHER
from nova_tts.voice_models import VOICE_MODELS_ROOT, list_voice_models
from nova_core.utils.logging import logger
from nova_core.utils.paths import get_project_root

# ------------------------------------------------------------------ vocabulary

STAGE_ENVIRONMENT = "environment"
STAGE_SYNTHESIS = "synthesis"
STAGE_PREPARATION = "preparation"
STAGE_QUALITY = "quality"
STAGE_TRAINING = "training"
STAGE_EXPORT = "export"
STAGE_LABELS = {
    STAGE_ENVIRONMENT: "準備訓練環境",
    STAGE_SYNTHESIS: "合成語料（Edge 測試用老師）",
    STAGE_PREPARATION: "整理語料",
    STAGE_QUALITY: "品質檢查",
    STAGE_TRAINING: "訓練（以底模為起點）",
    STAGE_EXPORT: "寫入聲線模型清單",
}
# Share of the overall progress bar; the Whisper check and the training run dominate.
STAGE_WEIGHTS = {
    STAGE_ENVIRONMENT: 2,
    STAGE_SYNTHESIS: 20,
    STAGE_PREPARATION: 8,
    STAGE_QUALITY: 15,
    STAGE_TRAINING: 55,
    STAGE_EXPORT: 5,
}

STAGE_PENDING, STAGE_RUNNING, STAGE_DONE, STAGE_FAILED, STAGE_CANCELLED = (
    "pending", "running", "done", "failed", "cancelled",
)
JOB_RUNNING, JOB_CANCELLING, JOB_DONE, JOB_FAILED, JOB_CANCELLED = (
    "running", "cancelling", "done", "failed", "cancelled",
)
ACTIVE_STATUSES = (JOB_RUNNING, JOB_CANCELLING)

CHECK_ENVIRONMENT = "environment"
CHECK_OTHER_JOB = "other_job"
CHECK_TRANSCRIPTION = "transcription"
CHECK_EDGE = "edge_acknowledgement"
CHECK_CORPUS = "corpus"
CHECK_NAME = "model_name"
CHECK_SIZE = "corpus_size"

# Below about 15 minutes of speech a corpus only gets a reminder (spec decision 15).
SMALL_CORPUS_SECONDS = 15 * 60
LOG_MEMORY_LINES = 2000
LOG_LINE_CHARS = 2000
LOG_PAGE_LINES = 500
KEEP_JOB_FILES = 20
JOBS_DIR_NAME = ".jobs"
LOG_FILE = "log.txt"
STEP_PATTERN = re.compile(r"step=(\d+)/(\d+)(?:\s+loss=([0-9.]+))?")
INTERRUPTED_MESSAGE = "伺服器重新啟動，訓練工作已中斷"
# A recorded pid may have been reused: only a process whose command line names one of the
# children this job starts (the training tools, the Whisper worker) is ever signalled.
ORPHAN_MARKERS = ("integrations/matcha-train/scripts", "nova_tts.training.whisper_worker")
# Server shutdown waits for the cancelled job this long beyond the SIGTERM grace period.
SHUTDOWN_MARGIN_SECONDS = 5.0
ORPHAN_KILL_WAIT_SECONDS = 5.0
ORPHAN_POLL_SECONDS = 0.1


# ------------------------------------------------------------------ data

class TrainingError(Exception):
    """A request problem; ``status`` is the HTTP status a route should answer with."""

    def __init__(
        self,
        message: str,
        status: int = 400,
        *,
        preflight: Preflight | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.preflight = preflight
        self.extra = extra or {}


@dataclass(frozen=True)
class Preflight:
    checks: tuple[Check, ...]

    @property
    def can_start(self) -> bool:
        return not any(check.status == FAIL for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {"can_start": self.can_start, "checks": [check.to_dict() for check in self.checks]}


@dataclass(frozen=True)
class TrainingSettings:
    min_free_vram_gb: float = DEFAULT_MIN_FREE_VRAM_GB
    whisper_model: str = DEFAULT_WHISPER_MODEL
    min_similarity: float = DEFAULT_MIN_SIMILARITY
    cancel_grace_seconds: float = DEFAULT_GRACE_SECONDS
    whisper_utterance_timeout_seconds: float = UTTERANCE_TIMEOUT_SECONDS


@dataclass(frozen=True)
class TrainingParams:
    """Hyper-parameters of the fine-tuning run (not part of the request)."""

    batch_size: int = 16
    epochs: int = 35
    max_steps: int = 0
    learning_rate: float = 1e-4
    encoder_lr_scale: float = 0.2
    num_workers: int = 2
    vram_sample_seconds: float = 15.0


@dataclass(frozen=True)
class TrainingPaths:
    root: Path
    training_python: Path
    base_checkpoint: Path
    base_assets: Path
    tools_dir: Path
    voice_root: Path

    @classmethod
    def default(cls, voice_root: Path | None = None) -> TrainingPaths:
        root = get_project_root()
        return cls(
            root=root,
            training_python=root / ".local" / "matcha-train" / "venv" / "bin" / "python",
            base_checkpoint=root / ".local" / "matcha-base" / "pytorch_model_sherpa.bin",
            base_assets=root / "models" / "tts" / "matcha-icefall-zh-en",
            tools_dir=root / "integrations" / "matcha-train" / "scripts",
            voice_root=VOICE_MODELS_ROOT if voice_root is None else voice_root,
        )

    def missing(self) -> list[str]:
        needed = {
            "訓練環境 .local/matcha-train/venv/": self.training_python,
            "底模權重 .local/matcha-base/pytorch_model_sherpa.bin": self.base_checkpoint,
            "底模資源 models/tts/matcha-icefall-zh-en/tokens.txt": self.base_assets / "tokens.txt",
            "底模資源 models/tts/matcha-icefall-zh-en/lexicon.txt": self.base_assets / "lexicon.txt",
            "底模資源 models/tts/matcha-icefall-zh-en/vocos-16khz-univ.onnx": self.base_assets / "vocos-16khz-univ.onnx",
        }
        return [label for label, path in needed.items() if not path.is_file()]


@dataclass(frozen=True)
class StartRequest:
    corpus: str
    name: str
    voice: str | None = None
    preset: str | None = None
    sentences: str | None = None


class JobCancelled(Exception):
    pass


class JobFailed(Exception):
    pass


@dataclass
class StageState:
    id: str
    status: str = STAGE_PENDING
    detail: str = ""
    progress: float = 0.0
    started_at: float | None = None
    seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": STAGE_LABELS[self.id],
            "status": self.status,
            "detail": self.detail,
            "progress": round(self.progress, 3),
            "seconds": None if self.seconds is None else round(self.seconds, 1),
        }


class JobLog:
    """Bounded in-memory log with absolute line numbers, mirrored to a file."""

    def __init__(self, path: Path | None, capacity: int = LOG_MEMORY_LINES) -> None:
        self._lines: collections.deque[str] = collections.deque(maxlen=capacity)
        self._total = 0
        self._lock = threading.Lock()
        self._file = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = path.open("a", encoding="utf-8")

    def append(self, line: str) -> None:
        line = line.rstrip("\r\n")[:LOG_LINE_CHARS]
        with self._lock:
            self._lines.append(line)
            self._total += 1
            if self._file is not None:
                self._file.write(line + "\n")
                self._file.flush()

    def read(self, offset: int = 0, limit: int = LOG_PAGE_LINES) -> dict[str, Any]:
        """Lines from absolute line number ``offset``; ``start`` is the first one returned.

        ``start`` is later than ``offset`` when the memory buffer has already dropped
        the older lines (the full log is in the file).
        """
        with self._lock:
            first = self._total - len(self._lines)
            start = min(max(offset, first), self._total)
            lines = list(self._lines)[start - first : start - first + limit]
            return {"start": start, "lines": lines, "next": start + len(lines), "total": self._total}

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None


@dataclass
class Job:
    id: str
    corpus: str
    name: str
    voice_id: str
    usage: str
    source: str
    stages: list[StageState]
    log: JobLog
    status: str = JOB_RUNNING
    error: str = ""
    message: str = ""
    started_at: float = 0.0
    finished_at: float | None = None
    process: Any = None  # the running child (training, export or Whisper), if any
    metrics: dict[str, Any] = field(default_factory=dict)
    cancel: threading.Event = field(default_factory=threading.Event)
    lock: threading.RLock = field(default_factory=threading.RLock)

    @property
    def active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    @property
    def pid(self) -> int | None:
        process = self.process
        return getattr(process, "pid", None) if process is not None else None

    def note(self, **metrics: Any) -> None:
        with self.lock:
            self.metrics.update(metrics)

    def stage(self, stage_id: str) -> StageState:
        return next(stage for stage in self.stages if stage.id == stage_id)

    def progress(self) -> int:
        total = sum(STAGE_WEIGHTS[stage.id] for stage in self.stages)
        done = sum(
            STAGE_WEIGHTS[stage.id] * (1.0 if stage.status == STAGE_DONE else stage.progress)
            for stage in self.stages
        )
        return 100 if self.status == JOB_DONE else min(99, int(100 * done / total))

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            current = next((s.id for s in self.stages if s.status == STAGE_RUNNING), None)
            return {
                "id": self.id,
                "corpus": self.corpus,
                "name": self.name,
                "voice_id": self.voice_id,
                "usage": self.usage,
                "source": self.source,
                "status": self.status,
                "stage": current,
                "stages": [stage.to_dict() for stage in self.stages],
                "progress": self.progress(),
                "message": self.message,
                "error": self.error,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "metrics": dict(self.metrics),
                "log_lines": self.log.read(0, 0)["total"],
            }


# ------------------------------------------------------------------ the manager

TranscriberFactory = Callable[[str], AbstractContextManager[Transcriber]]
BundleVerifier = Callable[[Path, threading.Event], None]


def _explain(reasons: Iterable[str], counts: Any) -> str:
    """The administrator-facing sentence for ``Corpus.trainability`` reason codes."""
    messages = {
        REASON_SOURCE_MISSING: "尚未宣告語料來源",
        REASON_PENDING_LINES: f"還有 {counts.pending} 句待確認",
        REASON_NO_CONFIRMED_LINES: "沒有已確認的句子",
        REASON_UNRESOLVED_DIGITS: "有已確認的句子含無法展開的數字，請改成中文字",
    }
    return "；".join(messages[reason] for reason in reasons)


class TrainingJobManager:
    """Pre-flight checks, the single running job, its log and persisted state.

    Every collaborator that touches the outside (``nvidia-smi``, children, Edge, the
    clock) is a keyword argument so tests run without any.
    """

    def __init__(
        self,
        *,
        store: CorpusStore | None = None,
        paths: TrainingPaths | None = None,
        settings: Callable[[], TrainingSettings] = TrainingSettings,
        params: TrainingParams | None = None,
        vram_probe: Callable[[], VramReading] = read_free_vram,
        spawn: Spawn = spawn_process,
        synthesize: Callable[..., edge_teacher.SynthesisReport] = edge_teacher.run_synthesis,
        transcriber_factory: TranscriberFactory | None = None,
        verify_bundle: BundleVerifier | None = None,
        orphan_stopper: Callable[[int], bool] | None = None,
        transcription_active: Callable[[], bool] = lambda: False,
        jobs_dir: Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = CorpusStore() if store is None else store
        self.paths = TrainingPaths.default() if paths is None else paths
        self._settings = settings
        self.params = TrainingParams() if params is None else params
        self._vram_probe = vram_probe
        self._spawn = spawn
        self._synthesize = synthesize
        self._transcriber_factory = transcriber_factory or self._default_transcriber
        self._verify_bundle = verify_bundle or self._default_verify
        self._orphan_stopper = orphan_stopper or self._stop_orphan
        self._transcription_active = transcription_active
        self._jobs_dir = self.store.root / JOBS_DIR_NAME if jobs_dir is None else jobs_dir
        self._clock = clock
        self._lock = threading.RLock()
        self._job: Job | None = None
        self._thread: threading.Thread | None = None
        self._recovered = False
        self._last: dict[str, Any] | None = None

    # ------------------------------------------------------------ pre-flight

    def settings(self) -> TrainingSettings:
        return self._settings()

    def evaluate_preflight(self, corpus: str | None = None, name: str | None = None) -> Preflight:
        """Every check with its reason; blocking (``nvidia-smi``, files), call it from a thread."""
        settings = self.settings()
        checks = [
            free_vram_check(self._vram_probe(), settings.min_free_vram_gb),
            self._environment_check(),
            self._other_job_check(),
            self._transcription_check(),
        ]
        checks.extend(self._corpus_checks(corpus))
        checks.append(self._name_check(name))
        return Preflight(tuple(checks))

    def _environment_check(self) -> Check:
        missing = self.paths.missing()
        if missing:
            return Check(
                CHECK_ENVIRONMENT, "訓練環境", FAIL,
                f"找不到 {'、'.join(missing)}；請執行 services/tts/scripts/setup-matcha-train.sh", {"missing": missing},
            )
        return Check(CHECK_ENVIRONMENT, "訓練環境", PASS, "訓練環境與底模權重已就緒")

    def _other_job_check(self) -> Check:
        with self._lock:
            job = self._job
        if job is not None and job.active:
            return Check(CHECK_OTHER_JOB, "其他訓練工作", FAIL, "已有一件進行中，同一時間只進行一件", {"job_id": job.id})
        return Check(CHECK_OTHER_JOB, "其他訓練工作", PASS, "沒有進行中的訓練工作")

    def _transcription_check(self) -> Check:
        if self._transcription_active():
            return Check(
                CHECK_TRANSCRIPTION, "自動逐字稿", FAIL,
                "正在自動產生逐字稿，與訓練共用 GPU 與 CPU；請等它完成或取消後再開始",
            )
        return Check(CHECK_TRANSCRIPTION, "自動逐字稿", PASS, "沒有進行中的自動逐字稿")

    def _corpus_checks(self, slug: str | None) -> list[Check]:
        if slug is None:
            return [Check(CHECK_CORPUS, "逐字稿確認", FAIL, "尚未選擇訓練語料")]
        try:
            corpus = self.store.get(slug)
        except CorpusError as exc:
            return [Check(CHECK_CORPUS, "逐字稿確認", FAIL, exc.message)]
        checks: list[Check] = []
        is_edge = corpus.source == SOURCE_EDGE_TEST_TEACHER
        if is_edge:
            checks.append(self._edge_check(slug))
        reasons = list(corpus.trainability().reasons)
        if is_edge and not corpus.counts.confirmed:
            # The synthesis stage creates the lines; trainability is checked again after it.
            reasons = [reason for reason in reasons if reason != REASON_NO_CONFIRMED_LINES]
        counts = corpus.counts
        detail = {"pending": counts.pending, "confirmed": counts.confirmed, "excluded": counts.excluded, "reasons": reasons}
        if reasons:
            checks.append(Check(CHECK_CORPUS, "逐字稿確認", FAIL, _explain(reasons, counts), detail))
        elif is_edge and not counts.confirmed:
            checks.append(Check(CHECK_CORPUS, "逐字稿確認", PASS, "合成後會再檢查一次", detail))
        else:
            checks.append(Check(CHECK_CORPUS, "逐字稿確認", PASS, f"已確認 {counts.confirmed} 句", detail))
        confirmed = [line for line in corpus.lines if line.review == REVIEW_CONFIRMED]
        if confirmed:
            seconds = sum(estimate_seconds(line.text) for line in confirmed)
            detail = {"estimated_seconds": round(seconds), "threshold_seconds": SMALL_CORPUS_SECONDS}
            if seconds < SMALL_CORPUS_SECONDS:
                checks.append(Check(
                    CHECK_SIZE, "語料份量", WARN,
                    f"估計約 {seconds / 60:.0f} 分鐘，低於約 15 分鐘；可以開始，但音質與穩定度通常較差", detail,
                ))
            else:
                checks.append(Check(CHECK_SIZE, "語料份量", PASS, f"估計約 {seconds / 60:.0f} 分鐘", detail))
        return checks

    def _edge_check(self, slug: str) -> Check:
        label = f"Edge 條文確認（{MSA_CLAUSE.reference}）"
        try:
            record = require_acknowledgement(self.store, slug)
        except CorpusError as exc:
            return Check(CHECK_EDGE, label, FAIL, exc.message)
        return Check(CHECK_EDGE, label, PASS, "已確認", {"acknowledged_at": record.acknowledged_at})

    def _name_check(self, name: str | None) -> Check:
        try:
            cleaned = check_model_name(name, [model.name for model in list_voice_models(self.paths.voice_root)])
        except BundleError as exc:
            return Check(CHECK_NAME, "聲線模型名稱", FAIL, exc.message)
        return Check(CHECK_NAME, "聲線模型名稱", PASS, "有效且不重名", {"name": cleaned})

    # ------------------------------------------------------------ status

    def job_active(self) -> bool:
        """Whether a job holds the GPU: from ``start`` until its worker has settled it.

        Done, failed (an exited child included) and cancelled are settled; ``cancelling``
        is not, because the child may still be on the GPU.
        """
        with self._lock:
            job = self._job
        return job is not None and job.active

    def status(self) -> dict[str, Any] | None:
        """The running job, else the latest finished one, else ``None``."""
        with self._lock:
            job, last = self._job, self._last
        return job.snapshot() if job is not None else last

    def read_log(self, offset: int = 0, limit: int = LOG_PAGE_LINES) -> dict[str, Any]:
        with self._lock:
            job, last = self._job, self._last
        if job is not None:
            return {"job_id": job.id, **job.log.read(offset, limit)}
        if last is not None:  # after a restart: the log file of the last job
            return {"job_id": last["id"], **self._read_log_file(last, offset, limit)}
        return {"job_id": None, "start": 0, "lines": [], "next": 0, "total": 0}

    def _read_log_file(self, job: dict[str, Any], offset: int, limit: int) -> dict[str, Any]:
        try:
            lines = (self._workdir(job["corpus"], job["id"]) / LOG_FILE).read_text(encoding="utf-8").splitlines()
        except (OSError, KeyError, ValueError):
            lines = []
        start = min(max(offset, 0), len(lines))
        page = lines[start : start + limit]
        return {"start": start, "lines": page, "next": start + len(page), "total": len(lines)}

    def join(self, timeout: float | None = None) -> None:
        """Wait for the worker thread (tests; the server never waits)."""
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout)

    # ------------------------------------------------------------ start and cancel

    def start(self, request: StartRequest) -> dict[str, Any]:
        """Check, then run the job in a worker thread; raises ``TrainingError`` with the reasons.

        The slow checks (``nvidia-smi``, files) run without the manager's lock; under the lock
        only the cheap exclusivity checks are repeated and the job is registered.
        """
        sentences = self._sentences_of(request)
        preflight = self.evaluate_preflight(request.corpus, request.name)
        if not preflight.can_start:
            raise self._refusal(preflight)
        corpus = self.store.get(request.corpus)
        known = list_voice_models(self.paths.voice_root)
        name = check_model_name(request.name, [model.name for model in known])
        is_edge = corpus.source == SOURCE_EDGE_TEST_TEACHER
        job_id = f"job-{time.strftime('%Y%m%d-%H%M%S', time.localtime(self._clock()))}-{secrets.token_hex(2)}"
        voice_id = new_model_id(model.id for model in known)
        workdir = self._workdir(corpus.slug, job_id)
        stage_ids = [
            STAGE_ENVIRONMENT,
            STAGE_SYNTHESIS if is_edge else STAGE_PREPARATION,
            STAGE_QUALITY,
            STAGE_TRAINING,
            STAGE_EXPORT,
        ]
        with self._lock:
            # Another start or a transcription may have begun since the pre-flight looked.
            # Once the job is registered, POST /offer refuses new stages; the core checks
            # for a stage that connected meanwhile once this returns.
            fresh = {check.id: check for check in (self._other_job_check(), self._transcription_check())}
            if any(check.status == FAIL for check in fresh.values()):
                raise self._refusal(Preflight(tuple(fresh.get(check.id, check) for check in preflight.checks)))
            job = Job(
                id=job_id,
                corpus=corpus.slug,
                name=name,
                voice_id=voice_id,
                usage=corpus.usage_label(),
                source=corpus.source or "",
                stages=[StageState(stage_id) for stage_id in stage_ids],
                log=JobLog(workdir / LOG_FILE),
                started_at=self._clock(),
            )
            self._job = job
            thread = threading.Thread(
                target=self._run, args=(job, request, sentences), name=f"matcha-training-{job_id}", daemon=True
            )
            self._thread = thread
        self._persist(job)
        job.log.append(f"訓練工作 {job_id}：語料 {corpus.slug}，聲線模型「{name}」（ID {voice_id}），標示 {job.usage}")
        thread.start()
        return job.snapshot()

    @staticmethod
    def _refusal(preflight: Preflight) -> TrainingError:
        reasons = "；".join(f"{check.label}：{check.reason}" for check in preflight.checks if check.status == FAIL)
        return TrainingError(f"目前不能開始訓練：{reasons}", 409, preflight=preflight)

    def cancel(self) -> dict[str, Any] | None:
        """Ask the running job to stop; ``None`` when nothing is running.

        Whether the job is still running is decided under the job's lock, so a job that
        has just finished is never turned back into ``cancelling``.
        """
        with self._lock:
            job = self._job
        if job is None:
            return None
        with job.lock:
            if not job.active:
                return None
            job.status = JOB_CANCELLING
            job.message = "正在取消，釋放 GPU…"
            job.cancel.set()
        job.log.append("收到取消要求")
        return job.snapshot()

    def shutdown(self, timeout: float | None = None) -> None:
        """Cancel the running job and wait for its child to be gone; for the server's shutdown.

        The worker sends SIGTERM and, after the grace period, SIGKILL. If it has not finished
        within ``timeout`` (default: the grace period plus a margin) the child is killed
        outright, so the GPU is free when the server exits. Blocking: run it in a thread.
        """
        with self._lock:
            job, thread = self._job, self._thread
        if job is None or thread is None or not job.active:
            return
        self.cancel()
        limit = self.settings().cancel_grace_seconds + SHUTDOWN_MARGIN_SECONDS if timeout is None else timeout
        thread.join(limit)
        if thread.is_alive():
            child = job.process
            if child is not None:
                logger.warning("Training job %s did not stop in %.0f s; killing its child", job.id, limit)
                child.kill()
            thread.join(SHUTDOWN_MARGIN_SECONDS)

    def _sentences_of(self, request: StartRequest) -> list[str] | None:
        """The sentences an Edge job synthesises; validated before anything is created."""
        try:
            corpus = self.store.get(request.corpus)
        except CorpusError:
            return None  # the pre-flight check reports it
        if corpus.source != SOURCE_EDGE_TEST_TEACHER:
            return None
        try:
            if request.voice is not None and request.voice not in edge_teacher.EDGE_ZH_TW_VOICES:
                raise CorpusError("不明的 Edge 聲音")
            if request.sentences is not None:
                return self._resolved_sentences(request.sentences)
            if request.preset is not None:
                return select_preset(request.preset)
        except CorpusError as exc:
            raise TrainingError(exc.message, exc.status) from exc
        raise TrainingError("Edge 語料要選擇份量（" + "、".join(PRESETS) + "）或提供朗讀文字")

    @staticmethod
    def _resolved_sentences(raw: str) -> list[str]:
        """An administrator's list, refused with 409 while any digit is left unexpanded.

        The same review as ``POST /api/tts/training/text-preview``, so a list that shows
        ``ok`` there is accepted here.
        """
        review = review_text_list(raw)
        if review.ok:
            return [item.text for item in review.sentences]
        unresolved = [
            {"index": item.index, "text": fragment.text, "reason": fragment.reason}
            for item in review.sentences
            for fragment in item.unresolved
        ]
        listing = "；".join(f"第 {entry['index']} 句「{entry['text']}」" for entry in unresolved)
        raise TrainingError(
            f"有數字無法確定怎麼念，請先改寫或移除再開始：{listing}", 409, extra={"unresolved": unresolved}
        )

    # ------------------------------------------------------------ the worker

    def _run(self, job: Job, request: StartRequest, sentences: list[str] | None) -> None:
        workdir = self._workdir(job.corpus, job.id)
        try:
            self._environment(job, workdir)
            if sentences is not None:
                self._synthesis(job, request, sentences)
            else:
                self._preparation(job, workdir)
            self._quality(job, workdir)
            result = self._training(job, workdir)
            self._export(job, workdir, result)
            with job.lock:
                job.status = JOB_DONE
                job.message = f"完成：聲線模型「{job.name}」已寫入清單（{job.usage}）"
        except JobCancelled:
            with job.lock:
                job.status = JOB_CANCELLED
                job.message = "已取消，語料保留，訓練進度不保留，GPU 已釋放"
                for stage in job.stages:
                    if stage.status == STAGE_RUNNING:
                        stage.status = STAGE_CANCELLED
        except JobFailed as exc:
            self._fail(job, str(exc))
        except CorpusError as exc:
            self._fail(job, exc.message)
        except Exception as exc:
            logger.exception("Matcha training job %s failed", job.id)
            self._fail(job, f"{type(exc).__name__}: {exc}")
        finally:
            self._finish(job, workdir)

    def _fail(self, job: Job, reason: str) -> None:
        with job.lock:
            job.status = JOB_FAILED
            job.error = reason
            job.message = f"失敗：{reason}"
            for stage in job.stages:
                if stage.status == STAGE_RUNNING:
                    stage.status = STAGE_FAILED
        job.log.append(f"失敗：{reason}")

    def _finish(self, job: Job, workdir: Path) -> None:
        with job.lock:
            job.finished_at = self._clock()
            job.process = None
        job.log.append(f"工作結束：{job.status}")
        job.log.close()
        for child in workdir.iterdir() if workdir.is_dir() else ():
            if child.name == LOG_FILE:
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        with self._lock:
            self._last = job.snapshot()
        self._persist(job)
        self._prune_job_files()

    # -- stage plumbing

    def _begin(self, job: Job, stage_id: str, detail: str = "") -> StageState:
        if job.cancel.is_set():
            raise JobCancelled
        with job.lock:
            stage = job.stage(stage_id)
            stage.status, stage.detail, stage.started_at = STAGE_RUNNING, detail, self._clock()
            job.message = STAGE_LABELS[stage_id]
        job.log.append(f"[{STAGE_LABELS[stage_id]}] 開始")
        self._persist(job)
        return stage

    def _end(self, job: Job, stage: StageState, detail: str | None = None, *, cancellable: bool = True) -> None:
        if cancellable and job.cancel.is_set():
            raise JobCancelled
        with job.lock:
            stage.status, stage.progress = STAGE_DONE, 1.0
            stage.seconds = self._clock() - (stage.started_at or self._clock())
            if detail is not None:
                stage.detail = detail
        job.log.append(f"[{STAGE_LABELS[stage.id]}] 完成：{stage.detail}（{stage.seconds:.0f} 秒）")
        self._persist(job)

    def _update(self, job: Job, stage: StageState, progress: float, detail: str) -> None:
        with job.lock:
            stage.progress, stage.detail = min(max(progress, 0.0), 1.0), detail

    # -- stages

    def _environment(self, job: Job, workdir: Path) -> None:
        stage = self._begin(job, STAGE_ENVIRONMENT)
        missing = self.paths.missing()
        if missing:
            raise JobFailed(f"找不到 {'、'.join(missing)}")
        workdir.mkdir(parents=True, exist_ok=True)
        self._end(job, stage, "訓練環境與底模權重已就緒")

    def _synthesis(self, job: Job, request: StartRequest, sentences: list[str]) -> None:
        stage = self._begin(job, STAGE_SYNTHESIS, f"{len(sentences)} 句")
        voice = request.voice or edge_teacher.DEFAULT_VOICE

        def on_progress(item: edge_teacher.Progress) -> None:
            self._update(job, stage, item.index / max(item.total, 1), f"{item.index}/{item.total}")
            if item.status in (edge_teacher.STATUS_REJECTED, edge_teacher.STATUS_FAILED):
                job.log.append(f"[合成] 第 {item.index} 句 {item.status}：{item.reason}")

        report = self._synthesize(
            self.store, job.corpus, sentences, voice=voice, cancel=job.cancel, on_progress=on_progress
        )
        if report.cancelled or job.cancel.is_set():
            raise JobCancelled
        if report.aborted:
            raise JobFailed(
                f"Edge 連續拒絕合成要求，已中止（已存 {report.stored} 句，保留可續做）；請稍後再開始"
            )
        summary = (
            f"新增 {report.stored} 句，略過 {report.skipped}，不合格 {report.rejected}，失敗 {report.failed}，"
            f"待校對 {report.needs_review}"
        )
        if not report.stored and not report.skipped:
            raise JobFailed("沒有合成出任何句子：" + summary)
        self._end(job, stage, summary)

    def _preparation(self, job: Job, workdir: Path) -> None:
        stage = self._begin(job, STAGE_PREPARATION)
        self._check_trainable(job)
        report = convert_uploads(
            self.store, job.corpus, workdir, cancel=job.cancel,
            on_progress=lambda done, total: self._update(job, stage, done / max(total, 1), f"{done}/{total}"),
        )
        self._log_excluded(job, "整理", report)
        if report.cancelled:
            raise JobCancelled
        self._end(job, stage, f"轉成 16 kHz 單聲道 {report.done} 句，排除 {len(report.excluded)} 句")

    def _quality(self, job: Job, workdir: Path) -> None:
        stage = self._begin(job, STAGE_QUALITY)
        # Training starts only from a fully confirmed corpus: after the Edge synthesis too.
        self._check_trainable(job)
        settings = self.settings()
        audio = check_quality(
            self.store, job.corpus, workdir, cancel=job.cancel,
            on_progress=lambda done, total: self._update(job, stage, 0.3 * done / max(total, 1), f"音檔 {done}/{total}"),
        )
        self._log_excluded(job, "音檔品質", audio)
        if audio.cancelled:
            raise JobCancelled
        job.log.append(f"[品質檢查] 音檔檢查：通過 {audio.done} 句，排除 {len(audio.excluded)} 句")
        if not audio.done:
            raise JobFailed("沒有任何句子通過音檔品質檢查")
        job.log.append(f"[品質檢查] Whisper（{settings.whisper_model}，CPU）比對逐字稿；這一步需要一段時間")
        try:
            with self._transcriber_factory(settings.whisper_model) as transcribe:
                report = verify_with_asr(
                    self.store, job.corpus, transcribe, min_similarity=settings.min_similarity, cancel=job.cancel,
                    on_progress=lambda done, total: self._update(
                        job, stage, 0.3 + 0.7 * done / max(total, 1), f"逐字稿比對 {done}/{total}"
                    ),
                )
        except TranscriberError as exc:
            if job.cancel.is_set():  # the cancel killed the child; that is not a failure
                raise JobCancelled from exc
            raise JobFailed(str(exc)) from exc
        finally:
            with job.lock:
                job.process = None
            self._persist(job)
        if report.cancelled or job.cancel.is_set():
            raise JobCancelled
        for mismatch in report.excluded:
            job.log.append(f"[品質檢查] 排除第 {mismatch.line_id} 句：相似度 {mismatch.similarity:.2f}（念出「{mismatch.heard}」，文字「{mismatch.expected}」）")
        # Training refuses a corpus that is not fully confirmed: check once more, now.
        self._check_trainable(job)
        remaining = self.store.get(job.corpus).counts.confirmed
        job.note(lines=remaining)
        self._end(job, stage, f"{remaining} 句可訓練；音檔排除 {len(audio.excluded)} 句，逐字稿不符排除 {len(report.excluded)} 句")

    def _check_trainable(self, job: Job) -> None:
        corpus = self.store.get(job.corpus)
        trainability = corpus.trainability()
        if not trainability.trainable:
            raise JobFailed("語料不能訓練：" + _explain(trainability.reasons, corpus.counts))

    def _log_excluded(self, job: Job, label: str, report: PreparationReport) -> None:
        for item in report.excluded:
            job.log.append(f"[{label}] 排除第 {item.line_id} 句：{'、'.join(item.reasons)}")

    def _training(self, job: Job, workdir: Path) -> dict[str, Any]:
        stage = self._begin(job, STAGE_TRAINING)
        lines = self.store.get(job.corpus).training_lines()
        manifest = build_manifest(lines, workdir, self.paths.base_assets, tools_dir=self.paths.tools_dir)
        for line_id, reason in manifest.skipped:
            job.log.append(f"[訓練] 略過第 {line_id} 句：{reason}")
        if not manifest.written:
            raise JobFailed("沒有可以訓練的句子")
        params = self.params
        checkpoints = workdir / "checkpoints"
        command = [
            str(self.paths.training_python), str(self.paths.tools_dir / "train_matcha.py"),
            "--manifest", str(manifest.manifest),
            "--base-ckpt", str(self.paths.base_checkpoint),
            "--out-dir", str(checkpoints),
            "--batch-size", str(params.batch_size),
            "--epochs", str(params.epochs),
            "--max-steps", str(params.max_steps),
            "--lr", str(params.learning_rate),
            "--encoder-lr-scale", str(params.encoder_lr_scale),
            "--num-workers", str(params.num_workers),
        ]
        started = self._clock()
        self._update(job, stage, 0.0, f"{manifest.written} 句")
        job.note(lines=manifest.written, training_started_at=started)

        def on_line(text: str) -> None:
            job.log.append(text)
            match = STEP_PATTERN.search(text)
            if match:
                step, total = int(match.group(1)), int(match.group(2))
                loss = f"，損失 {match.group(3)}" if match.group(3) else ""
                self._update(job, stage, step / max(total, 1), f"步數 {step}/{total}{loss}")
                job.note(step=step, total_steps=total)

        sampler_stop = threading.Event()
        sampler = threading.Thread(target=self._sample_vram, args=(job, sampler_stop), daemon=True)
        sampler.start()
        try:
            result = run_process(
                self._tracked_spawn(job), command, self._child_env(), self.paths.root, on_line, job.cancel,
                grace_seconds=self.settings().cancel_grace_seconds,
            )
        finally:
            sampler_stop.set()
            sampler.join(5)
        with job.lock:
            job.process = None
        job.note(training_seconds=round(self._clock() - started, 1))
        if result.cancelled or job.cancel.is_set():
            raise JobCancelled
        if result.returncode != 0:
            raise JobFailed(f"訓練程序失敗（結束碼 {result.returncode}），詳見日誌")
        checkpoint = next((p for p in (checkpoints / "best.pt", checkpoints / "last.pt") if p.is_file()), None)
        if checkpoint is None:
            raise JobFailed("訓練結束但沒有產生權重檔")
        self._end(job, stage, f"{job.metrics.get('step', '?')} 步，{job.metrics['training_seconds']:.0f} 秒")
        return {"checkpoint": checkpoint, "lexicon": manifest.lexicon}

    def _sample_vram(self, job: Job, stop: threading.Event) -> None:
        """Record the lowest free memory seen while training, to calibrate the threshold."""
        interval = self.params.vram_sample_seconds
        if interval <= 0:
            return
        while True:
            reading = self._vram_probe()
            if reading.free_mib is not None:
                with job.lock:
                    low = job.metrics.get("min_free_vram_mib")
                    if low is None or reading.free_mib < low:
                        job.metrics["min_free_vram_mib"] = reading.free_mib
                        job.log.append(f"[訓練] 剩餘顯存 {reading.free_mib} MiB")
            if stop.wait(interval):
                return

    def _export(self, job: Job, workdir: Path, trained: dict[str, Any]) -> None:
        stage = self._begin(job, STAGE_EXPORT)
        staging = workdir / "export"
        command = [
            str(self.paths.training_python), str(self.paths.tools_dir / "export_matcha_onnx.py"),
            "--ckpt", str(trained["checkpoint"]),
            "--output-dir", str(staging),
            "--base-assets", str(self.paths.base_assets),
            "--lexicon", str(trained["lexicon"]),
        ]
        result = run_process(
            self._tracked_spawn(job), command, self._child_env(), self.paths.root,
            lambda text: job.log.append(text), job.cancel, grace_seconds=self.settings().cancel_grace_seconds,
        )
        if result.cancelled or job.cancel.is_set():
            raise JobCancelled
        if result.returncode != 0:
            raise JobFailed(f"匯出程序失敗（結束碼 {result.returncode}），詳見日誌")
        self._update(job, stage, 0.6, "檢查 sherpa-onnx 能否載入")
        self._verify_bundle(staging, job.cancel)
        if job.cancel.is_set():
            raise JobCancelled
        corpus = self.store.get(job.corpus)
        detail = ""
        if corpus.source == SOURCE_EDGE_TEST_TEACHER:
            detail = "Edge test teacher"
        install_voice_model(
            staging,
            job.voice_id,
            name=job.name,
            usage=corpus.usage_label(),
            source=source_description(corpus.source or "unknown", detail),
            root=self.paths.voice_root,
        )
        # The model is in the list now: a late cancel must not report it as cancelled.
        self._end(job, stage, f"models/tts/{job.voice_id}/", cancellable=False)

    # -- children

    def _tracked_spawn(self, job: Job) -> Spawn:
        def spawn(command, env, cwd):
            process = self._spawn(command, env, cwd)
            with job.lock:
                job.process = process
            self._persist(job)
            return process

        return spawn

    def _child_env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")}
        env["PYTHONNOUSERSITE"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        # cuDNN attention loads NVRTC by soname, outside PyTorch's wheel search paths.
        venv = self.paths.training_python.parent.parent
        nvrtc_dirs = [
            str(library.parent)
            for library in sorted(venv.glob("lib/python*/site-packages/nvidia/cuda_nvrtc/lib/libnvrtc.so.12"))
            if library.is_file()
        ]
        if nvrtc_dirs:
            inherited = env.get("LD_LIBRARY_PATH")
            if inherited:
                nvrtc_dirs.append(inherited)
            env["LD_LIBRARY_PATH"] = os.pathsep.join(nvrtc_dirs)
        return env

    def _default_transcriber(self, model: str) -> AbstractContextManager[Transcriber]:
        """The CPU Whisper child of the running job: tracked (its pid is saved), killed by cancel, timed."""
        with self._lock:
            job = self._job
        return SubprocessTranscriber(
            model,
            spawn=self._spawn if job is None else self._tracked_spawn(job),
            root=self.paths.root,
            utterance_timeout=self.settings().whisper_utterance_timeout_seconds,
            cancel=None if job is None else job.cancel,
        )

    def _default_verify(self, bundle: Path, cancel: threading.Event) -> None:
        lines: list[str] = []
        env = {**os.environ, "CUDA_VISIBLE_DEVICES": ""}
        result = run_process(
            self._spawn,
            [sys.executable, "-m", "nova_tts.training.verify_bundle", str(bundle)],
            env, self.paths.root, lines.append, cancel, grace_seconds=self.settings().cancel_grace_seconds,
        )
        if result.cancelled or cancel.is_set():
            return
        if result.returncode != 0:
            raise JobFailed("匯出的聲線模型無法被 sherpa-onnx 載入：" + (lines[-1] if lines else f"結束碼 {result.returncode}"))

    def _stop_orphan(self, pid: int) -> bool:
        return stop_orphan_training(pid, grace_seconds=self.settings().cancel_grace_seconds)

    # -- persistence

    def _workdir(self, slug: str, job_id: str) -> Path:
        return self.store.root / slug / "jobs" / job_id

    def _persist(self, job: Job) -> None:
        data = {**job.snapshot(), "pid": job.pid}
        self._jobs_dir.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(dir=self._jobs_dir, prefix=".tmp-")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)
            os.replace(name, self._jobs_dir / f"{job.id}.json")
        except OSError:
            logger.exception("Could not save training job state")
        finally:
            Path(name).unlink(missing_ok=True)

    def _prune_job_files(self) -> None:
        files = sorted(self._jobs_dir.glob("job-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for stale in files[KEEP_JOB_FILES:]:
            stale.unlink(missing_ok=True)

    def recover(self) -> None:
        """Once per process, at startup: jobs that were running when the server stopped are failed.

        Their children (training, export or the Whisper worker, by the pid saved in the job
        state) are stopped first, escalating to SIGKILL, so the GPU is free before the server
        accepts a request. Blocking: the server runs it in a worker thread.
        """
        with self._lock:
            if self._recovered:
                return
            self._recovered = True
        if not self._jobs_dir.is_dir():
            return
        latest: tuple[float, dict[str, Any]] | None = None
        for path in self._jobs_dir.glob("job-*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                mtime = path.stat().st_mtime
            except (OSError, ValueError):
                continue
            if data.get("status") in ACTIVE_STATUSES:
                pid = data.get("pid")
                if isinstance(pid, int) and self._orphan_stopper(pid):
                    logger.warning("Stopped training process %s left by an earlier server run", pid)
                data.update(status=JOB_FAILED, error=INTERRUPTED_MESSAGE, message=f"失敗：{INTERRUPTED_MESSAGE}", pid=None)
                for stage in data.get("stages", []):
                    if stage.get("status") == STAGE_RUNNING:
                        stage["status"] = STAGE_FAILED
                data["finished_at"] = data.get("finished_at") or self._clock()
                self._write_state(path, data)
            if latest is None or mtime > latest[0]:
                latest = (mtime, data)
        if latest is not None:
            with self._lock:
                self._last = latest[1]

    @staticmethod
    def _write_state(path: Path, data: dict[str, Any]) -> None:
        try:
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError:
            logger.exception("Could not update training job state %s", path)


def _read_command(pid: int) -> str:
    return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")


def _group_exists(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stop_orphan_training(
    pid: int,
    *,
    grace_seconds: float = DEFAULT_GRACE_SECONDS,
    kill_wait_seconds: float = ORPHAN_KILL_WAIT_SECONDS,
    signal_group: Callable[[int, int], None] = os.killpg,
    group_exists: Callable[[int], bool] = _group_exists,
    read_command: Callable[[int], str] = _read_command,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Stop a child process group left by an earlier server run; ``True`` if one was signalled.

    SIGTERM first, then SIGKILL when the group is still there after ``grace_seconds``, and
    a bounded wait (``kill_wait_seconds``) for it to disappear, so the GPU it held is free
    when this returns. A recorded pid may have been reused, so the group is signalled only
    when its command line names the training tools or the Whisper worker (``ORPHAN_MARKERS``).
    """
    try:
        command = read_command(pid)
    except OSError:
        return False
    if not any(marker in command for marker in ORPHAN_MARKERS):
        return False

    def gone_within(seconds: float) -> bool:
        deadline = clock() + seconds
        while group_exists(pid):
            if clock() >= deadline:
                return False
            sleep(ORPHAN_POLL_SECONDS)
        return True

    try:
        signal_group(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return False
    if gone_within(grace_seconds):
        return True
    try:
        signal_group(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return True
    if not gone_within(kill_wait_seconds):
        logger.error("Training process group %s survived SIGKILL", pid)
    return True
