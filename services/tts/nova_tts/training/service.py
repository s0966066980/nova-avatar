# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The voice-training half of the in-process TTS service (``VoiceTraining``).

Corpora (``corpus``), their automatic transcription (``transcription``) and the
training job (``jobs``) are TTS assets (ADR 0027); the console reaches them only
through the core, which calls these operations. Everything here is blocking: the
core calls it from a worker thread (CODING_STANDARDS 3).

The training gate is split (spec decision 14): the core checks for a connected
stage and the administrator, this layer judges free VRAM and everything else.
The pre-flight returned here therefore lists only the layer's own checks.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from nova_contracts.tts import (
    ClauseAcknowledged,
    ClauseAcknowledgement,
    CorpusCounts,
    CorpusCreation,
    CorpusDetail,
    CorpusLine,
    CorpusList,
    CorpusRef,
    CorpusSummary,
    EdgeClause,
    LineAdded,
    LineConfirmation,
    LineEdit,
    LineEdited,
    LinesConfirmed,
    LineRef,
    LineUpload,
    ReviewedSentence,
    TextListReview,
    TextReview,
    TrainingActivity,
    TrainingJob,
    TrainingJobState,
    TrainingLog,
    TrainingLogQuery,
    TrainingPreflight,
    TrainingQuery,
    TrainingSettings,
    TrainingStart,
    TrainingStatus,
    TranscriptImport,
    TranscriptionProgress,
    TranscriptionStart,
    TranscriptsApplied,
    TtsEngineSettings,
    TtsError,
    UnresolvedFragment,
)
from src.tts.training import jobs
from src.tts.training.corpus import Corpus, CorpusError, CorpusStore, Line
from src.tts.training.edge_acknowledgement import MSA_CLAUSE, record_acknowledgement
from src.tts.training.gpu_guard import DeviceChoice, choose_transcription_device
from src.tts.training.gpu_probe import VramReading, read_free_vram
from src.tts.training.ingest import create_uploaded_corpus, ingest_audio
from src.tts.training.numerals import NormalizedText, normalize_digits
from src.tts.training.sentences import review_text_list
from src.tts.training.transcription import TranscriptionJobs, TranscriptionStatus, cuda_available, default_factory
from src.tts.training.transcripts import (
    TranscriptEntry,
    TranscriptError,
    apply_transcripts,
    parse_metadata_csv,
    parse_txt,
)
from src.tts.training.usage import SOURCE_EDGE_TEST_TEACHER


@contextmanager
def _refusals() -> Iterator[None]:
    """Turn the training modules' refusals into the contract's ``TtsError``."""
    try:
        yield
    except TranscriptError as exc:
        raise TtsError(exc.message, status=exc.status, extra={"problems": list(exc.problems)}) from exc
    except CorpusError as exc:
        raise TtsError(exc.message, status=exc.status) from exc
    except jobs.TrainingError as exc:
        extra = dict(exc.extra)
        if exc.preflight is not None:
            extra = {"preflight": exc.preflight.to_dict(), **extra}
        raise TtsError(exc.message, status=exc.status, extra=extra) from exc


def _unresolved(normalized: NormalizedText) -> tuple[UnresolvedFragment, ...]:
    return tuple(
        UnresolvedFragment(text=item.text, start=item.start, end=item.end, reason=item.reason)
        for item in normalized.unresolved
    )


def _line(line: Line, normalized: NormalizedText | None = None) -> CorpusLine:
    normalized = normalized if normalized is not None else normalize_digits(line.text)
    return CorpusLine(
        id=line.id,
        original_name=line.original_name,
        text=line.text,
        normalized_text=normalized.text,
        unresolved=_unresolved(normalized),
        review=line.review,  # type: ignore[arg-type]  # one of corpus.REVIEW_STATES
    )


def _summary_fields(corpus: Corpus) -> dict[str, Any]:
    counts = corpus.counts
    trainability = corpus.trainability()
    return {
        "slug": corpus.slug,
        "source": corpus.source,
        "declared_at": corpus.declared_at,
        "usage_label": corpus.usage_label(),
        "counts": CorpusCounts(
            pending=counts.pending, confirmed=counts.confirmed, excluded=counts.excluded, total=len(corpus.lines)
        ),
        "trainable": trainability.trainable,
        "reasons": trainability.reasons,
    }


def _summary(corpus: Corpus) -> CorpusSummary:
    return CorpusSummary(**_summary_fields(corpus))


def _progress(status: TranscriptionStatus) -> TranscriptionProgress:
    return TranscriptionProgress.model_validate(
        {
            "state": status.state,
            "slug": status.slug,
            "model": status.model,
            "total": status.total,
            "done": status.done,
            "skipped": status.skipped,
            "failed": [{"line_id": item.line_id, "message": item.message} for item in status.failed],
            "message": status.message,
            "cancel_requested": status.cancel_requested,
            "device": status.device,
            "fallback_reason": status.fallback_reason,
        }
    )


def _job(snapshot: dict[str, Any] | None) -> TrainingJob | None:
    """A job snapshot (live or saved by an earlier process) as the contract's job."""
    if snapshot is None:
        return None
    return TrainingJob.model_validate({key: snapshot[key] for key in TrainingJob.model_fields if key in snapshot})


def _parse_transcript_files(request: TranscriptImport) -> list[TranscriptEntry]:
    """Parse every file; every problem of every file is reported together."""
    entries: list[TranscriptEntry] = []
    problems: list[str] = []
    for item in request.files:
        name = item.name
        try:
            if name.lower() == "metadata.csv":
                entries.extend(parse_metadata_csv(item.content))
            elif name.lower().endswith(".txt"):
                entries.append(parse_txt(name, item.content))
            else:
                shown = name.replace(chr(92), "/").rsplit("/", 1)[-1][:80]
                raise TranscriptError([f"「{shown}」不是支援的逐字稿檔，只接受 .txt 與 metadata.csv"])
        except TranscriptError as exc:
            problems.extend(exc.problems)
    if problems:
        raise TranscriptError(problems)
    return entries


class InProcessVoiceTraining:
    """Corpora, transcription and training jobs, served in-process.

    Tests inject ``corpus_store``, ``transcription`` and ``training_jobs``; by default
    they are the server's (``data/tts/training``, faster-whisper, the Matcha tools).
    """

    def __init__(
        self,
        *,
        settings: Callable[[], TtsEngineSettings],
        corpus_store: CorpusStore | None = None,
        transcription: TranscriptionJobs | None = None,
        training_jobs: jobs.TrainingJobManager | None = None,
        vram_probe: Callable[[], VramReading] = read_free_vram,
        cuda_available: Callable[[], bool] = cuda_available,
    ) -> None:
        self._training_settings = settings
        self._corpora = corpus_store if corpus_store is not None else CorpusStore()
        self._vram_probe = vram_probe
        self._cuda_available = cuda_available
        self._transcription = transcription if transcription is not None else TranscriptionJobs(
            self._corpora, default_factory, self._gpu_choice
        )
        self._training_jobs = training_jobs if training_jobs is not None else jobs.TrainingJobManager(
            store=self._corpora,
            settings=self._job_settings,
            transcription_active=self._transcription.running,
        )

    # ------------------------------------------------------------ lifecycle

    def _start_training(self) -> None:
        """At server startup: fail interrupted jobs and stop the children they left."""
        self._training_jobs.recover()

    def _stop_training(self) -> None:
        """At server shutdown: stop the transcription, cancel the job and free the GPU."""
        self._transcription.stop()
        self._training_jobs.shutdown()

    # ------------------------------------------------------------ settings

    def _job_settings(self) -> jobs.TrainingSettings:
        settings = self._training_settings()
        return jobs.TrainingSettings(
            min_free_vram_gb=settings.training_min_free_vram_gb,
            whisper_model=settings.training_whisper_model,
        )

    def _gpu_choice(self) -> DeviceChoice:
        """Free VRAM against the training threshold; the core already ruled out a stage."""
        threshold = self._training_settings().training_min_free_vram_gb
        return choose_transcription_device(self._vram_probe, threshold, self._cuda_available)

    # ------------------------------------------------------------ corpora

    def list_corpora(self) -> CorpusList:
        return CorpusList(corpora=tuple(_summary(corpus) for corpus in self._corpora.list()))

    def create_corpus(self, request: CorpusCreation) -> CorpusSummary:
        with _refusals():
            if request.source == SOURCE_EDGE_TEST_TEACHER:
                corpus = self._corpora.create(request.slug, source=SOURCE_EDGE_TEST_TEACHER)
            else:
                corpus = create_uploaded_corpus(self._corpora, request.slug, request.source, consent=request.consent)
        return _summary(corpus)

    def get_corpus(self, ref: CorpusRef) -> CorpusDetail:
        with _refusals():
            corpus = self._corpora.get(ref.slug)
        return CorpusDetail(
            **_summary_fields(corpus),
            lines=tuple(_line(row.line, row.normalized) for row in corpus.review_table()),
        )

    def add_line(self, audio: bytes, upload: LineUpload) -> LineAdded:
        with _refusals():
            result = ingest_audio(self._corpora, upload.slug, audio, upload.filename, upload.text)
        return LineAdded(line=_line(result.line), duration=round(result.duration, 2))

    def edit_line(self, request: LineEdit) -> LineEdited:
        with _refusals():
            if request.text is not None:
                self._corpora.set_text(request.slug, request.line_id, request.text)
            if request.review is not None:
                self._corpora.set_review(request.slug, request.line_id, request.review)
            corpus = self._corpora.get(request.slug)
        line = next(item for item in corpus.lines if item.id == request.line_id)
        return LineEdited(line=_line(line), summary=_summary(corpus))

    def line_audio(self, ref: LineRef) -> bytes:
        """An uploaded line's audio; Edge read-aloud output never leaves (ADR 0026)."""
        with _refusals():
            if self._corpora.get(ref.slug).source == SOURCE_EDGE_TEST_TEACHER:
                raise CorpusError("Edge 測試用老師合成的音檔不提供試聽或下載（ADR 0026）", status=403)
            return self._corpora.audio_path(ref.slug, ref.line_id).read_bytes()

    def import_transcripts(self, request: TranscriptImport) -> TranscriptsApplied:
        with _refusals():
            self._corpora.get(request.slug)
            result = apply_transcripts(self._corpora, request.slug, _parse_transcript_files(request))
        return TranscriptsApplied(applied=result.applied, without_transcript=tuple(result.without_transcript))

    def confirm_lines(self, request: LineConfirmation) -> LinesConfirmed:
        line_ids = None if request.line_ids is None else list(request.line_ids)
        with _refusals():
            result = self._corpora.confirm_pending(request.slug, line_ids)
            summary = _summary(self._corpora.get(request.slug))
        return LinesConfirmed(confirmed=result.confirmed, without_text=result.without_text, summary=summary)

    def acknowledge_clause(self, request: ClauseAcknowledgement) -> ClauseAcknowledged:
        with _refusals():
            record = record_acknowledgement(self._corpora, request.slug, request.shown_text)
        return ClauseAcknowledged(
            acknowledged_at=record.acknowledged_at,
            clause_reference=record.clause_reference,
            clause_effective=record.clause_effective,
        )

    # ------------------------------------------------------------ transcription

    def start_transcription(self, request: TranscriptionStart) -> TranscriptionProgress:
        line_ids = None if request.line_ids is None else list(request.line_ids)
        with _refusals():
            status = self._transcription.start(request.slug, line_ids, request.model, cpu_reason=request.cpu_reason)
        return _progress(status)

    def transcription_status(self, ref: CorpusRef) -> TranscriptionProgress:
        with _refusals():
            self._corpora.get(ref.slug)
        return _progress(self._transcription.status(ref.slug))

    def cancel_transcription(self, ref: CorpusRef) -> TranscriptionProgress:
        with _refusals():
            return _progress(self._transcription.cancel(ref.slug))

    # ------------------------------------------------------------ training jobs

    def training_status(self, query: TrainingQuery) -> TrainingStatus:
        manager = self._training_jobs
        settings = manager.settings()
        with _refusals():
            preflight = manager.evaluate_preflight(query.corpus, query.name).to_dict()
        return TrainingStatus(
            job=_job(manager.status()),
            preflight=TrainingPreflight.model_validate(preflight),
            settings=TrainingSettings(
                min_free_vram_gb=settings.min_free_vram_gb,
                whisper_model=settings.whisper_model,
                # The console shows and sends back exactly this text; it keeps no copy of its own.
                edge_clause=EdgeClause(
                    reference=MSA_CLAUSE.reference, effective=MSA_CLAUSE.effective, text=MSA_CLAUSE.text
                ),
            ),
        )

    def start_training(self, request: TrainingStart) -> TrainingJob:
        start = jobs.StartRequest(
            corpus=request.corpus,
            name=request.name,
            voice=request.voice,
            preset=request.preset,
            sentences=request.sentences,
        )
        with _refusals():
            job = _job(self._training_jobs.start(start))
        assert job is not None
        return job

    def cancel_training(self) -> TrainingJobState:
        return TrainingJobState(job=_job(self._training_jobs.cancel()))

    def training_log(self, query: TrainingLogQuery) -> TrainingLog:
        return TrainingLog.model_validate(self._training_jobs.read_log(query.offset))

    def training_activity(self) -> TrainingActivity:
        return TrainingActivity(active=self._training_jobs.job_active())

    def review_text_list(self, request: TextListReview) -> TextReview:
        with _refusals():
            review = review_text_list(request.sentences)
        return TextReview(
            ok=review.ok,
            total=review.total,
            unresolved_count=sum(len(item.unresolved) for item in review.sentences),
            estimated_seconds=round(review.estimated_seconds, 1),
            sentences=tuple(
                ReviewedSentence(
                    index=item.index,
                    text=item.text,
                    spoken=item.spoken,
                    unresolved=tuple(
                        UnresolvedFragment(text=u.text, start=u.start, end=u.end, reason=u.reason)
                        for u in item.unresolved
                    ),
                )
                for item in review.sentences
            ),
        )
