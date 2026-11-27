# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Speech-synthesis (TTS) layer contract.

Loopback shape (spec decision 7): ``POST /synthesize`` is one request per
playable fragment; the PCM comes back chunked as 16 kHz s16le and the core
cancels it by closing the connection. The voice library, voice models and voice
training are the TTS layer's assets (ADR 0027): the console reaches them only
through the core, which proxies them to the operations below.

In-process (spec decision 21) the real-time path does not go through
``synthesize``: the core opens one ``SpeechChannel`` per session from the
``TtsRuntime``, and the engine hands each 20 ms frame straight to the core's
``AudioSink`` on its own thread, as before the split (ADR 0007, 0008).
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Literal, Optional, Protocol, runtime_checkable

from pydantic import ConfigDict, Field, field_validator

from nova_contracts.common import ContractModel, ServiceError, ServiceHealth
from nova_contracts.http import (
    BinaryBody,
    HttpApi,
    HttpOperation,
    JsonBody,
    engine_operation,
    health_operation,
)

if TYPE_CHECKING:  # numpy is the caller's dependency, never this package's.
    import numpy as np

# "fake" speaks silence of a known length (spec decision 15): a configuration may
# name it for tests and rehearsals, but no console lists it.
TtsEngine = Literal["edgetts", "breezyvoice", "matcha", "fake"]
# The three preset sentences of a voice-model preview; callers never send text.
PreviewSentence = Literal["zh", "digits", "en"]

PCM_MEDIA_TYPE = "audio/L16;rate=16000"
# The largest reference recording the voice library accepts.
MAX_VOICE_UPLOAD_BYTES = 20 * 1024 * 1024


class TtsError(ServiceError):
    """A TTS refusal or failure: the operator-facing message and its HTTP status.

    ``extra`` holds JSON fields a console route adds next to the message (the
    failed training checks, the unresolved digits ...).
    """

    def __init__(self, message: str, *, status: int = 400, extra: Optional[dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.extra = dict(extra or {})


# ------------------------------------------------------------------ text

_EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0000FE0F"
    "\U0000200D"
    "]+"
)


def strip_visual_markup(text: str) -> str:
    """The text a TTS engine speaks: Markdown and emoji removed, lines joined.

    Not an HTML escape. The core uses it to tell whether a fragment has
    anything to say; the TTS layer applies it again before synthesis.
    """
    value = str(text or "")
    value = re.sub(r"!\[([^]]*)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"(?m)^\s{0,3}(?:#{1,6}|>|[-+*])\s+", "", value)
    value = re.sub(r"```(?:\w+)?|`", "", value)
    value = re.sub(r"[*_~]+", "", value)
    value = _EMOJI_RE.sub("", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r" *\n+ *", "，", value)
    return value.strip(" ，")


# ------------------------------------------------------------------ fragments


class FragmentEnvelope(ContractModel):
    """The turn identity a fragment carries; built from the core's TurnEnvelope."""

    model_config = ConfigDict(from_attributes=True)

    turn_id: str
    generation: int
    sequence: int


class PlayableFragment(ContractModel):
    """A reply fragment the core cut and the TTS layer synthesizes."""

    envelope: FragmentEnvelope
    text: str
    estimated_seconds: float = Field(ge=0)

    @field_validator("text")
    @classmethod
    def _has_text(cls, text: str) -> str:
        if not text.strip():
            raise ValueError("fragment text cannot be empty")
        return text

    @property
    def fragment_id(self) -> str:
        return f"{self.envelope.turn_id}:{self.envelope.sequence}"


# ------------------------------------------------------------------ voices and engine


class TtsVoice(ContractModel):
    """The voice a role speaks with: its engine and what that engine needs.

    ``voice`` is an Edge voice name, a voice-library ID (BreezyVoice) or a
    voice-model ID (Matcha); ``server`` a loopback BreezyVoice address and
    ``model`` a ``models/`` catalog ID, "" for the defaults. All are IDs the
    core validated (CODING_STANDARDS rule 1), never paths.
    """

    engine: TtsEngine
    voice: str = ""
    server: str = ""
    model: str = ""
    edge_persistent_worker: bool = True
    edge_prefetch: bool = True
    edge_connection_reuse: bool = True


class TtsEngineSettings(ContractModel):
    """What every voice of the process shares (``PUT /engine``)."""

    # The renderer's audio frame rate: one PCM frame is 1/frames_per_second s.
    frames_per_second: int = Field(default=50, ge=1, le=1000)
    # sherpa-onnx CPU threads; also the key of the shared loaded voice model.
    matcha_threads: int = Field(default=4, ge=1)
    # Voice training: refuse to start below this much free VRAM.
    training_min_free_vram_gb: float = Field(default=8.0, gt=0)
    # faster-whisper size of the pre-training transcript check (CPU).
    training_whisper_model: str = "small"


class VoicePreparation(ContractModel):
    """Make a voice ready to speak: start its BreezyVoice server, warm Edge."""

    voice: TtsVoice
    # Edge warm-up limit; ``None`` is the layer's default.
    timeout_seconds: Optional[float] = Field(default=None, gt=0)


class VoiceServerStatus(ContractModel):
    """Whether a voice's BreezyVoice server answers with its model now."""

    ready: bool
    # The normalized address the voice would use.
    url: str


class SynthesisRequest(ContractModel):
    """One playable fragment in one voice."""

    fragment: PlayableFragment
    voice: TtsVoice
    # Stop returning audio after this many seconds (a preview's bound).
    max_seconds: Optional[float] = Field(default=None, gt=0)


# ------------------------------------------------------------------ voice library and models


class LibraryVoice(ContractModel):
    """A reference recording of the voice library (參考音訊庫)."""

    id: str
    name: str
    seconds: float
    transcript: str
    # Recorded without the speaker's consent: for development only.
    development: bool = False


class VoiceList(ContractModel):
    voices: tuple[LibraryVoice, ...] = ()


class VoiceRef(ContractModel):
    voice_id: str


class VoiceUpload(ContractModel):
    """The fields sent with an uploaded reference recording."""

    name: str = Field(default="", max_length=1024)
    transcript: str = Field(default="", max_length=4096)


class VoiceModelInfo(ContractModel):
    """A voice model (聲線模型) under ``models/tts`` with its usage label."""

    id: str
    name: str
    usage: str
    languages: tuple[str, ...] = ()
    source: str


class TtsModel(ContractModel):
    """A BreezyVoice model folder under ``models/``, named by its catalog ID."""

    id: str


class TtsCatalog(ContractModel):
    """What a role's voice is chosen from."""

    voices: tuple[LibraryVoice, ...] = ()
    models: tuple[TtsModel, ...] = ()
    voice_models: tuple[VoiceModelInfo, ...] = ()


class VoiceModelPreview(ContractModel):
    """A preset sentence in a voice model's voice; no text of the caller's own."""

    voice_id: str
    sentence: PreviewSentence


# ------------------------------------------------------------------ voice training
# Corpora, transcription and training jobs (ticket 07 step 2, TTS part 2). The
# stage check and the administrator check of the training gate are the core's
# (spec decision 14): the layer's pre-flight lists only its own checks, and the
# core puts its two in front.

ReviewState = Literal["pending", "confirmed", "excluded"]
CheckStatus = Literal["pass", "fail", "warn"]
TranscriptionDevice = Literal["cuda", "cpu"]

# What the console routes enforce before a request reaches the layer.
MAX_CORPUS_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_TRANSCRIPT_TEXT_CHARS = 500
MAX_TRANSCRIPT_FILE_BYTES = 2 * 1024 * 1024
DEFAULT_TRANSCRIPTION_MODEL = "medium"


class CorpusRef(ContractModel):
    slug: str


class LineRef(ContractModel):
    slug: str
    line_id: str


class CorpusCounts(ContractModel):
    pending: int
    confirmed: int
    excluded: int
    total: int


class CorpusSummary(ContractModel):
    """A training corpus (訓練語料) with its source, usage label and trainability."""

    slug: str
    source: Optional[str] = None
    declared_at: Optional[str] = None
    usage_label: str
    counts: CorpusCounts
    trainable: bool
    reasons: tuple[str, ...] = ()


class UnresolvedFragment(ContractModel):
    """A token the digit normaliser would not guess; offsets index the original text."""

    text: str
    start: int
    end: int
    reason: str


class CorpusLine(ContractModel):
    """One recording of a corpus with its transcript and review state."""

    id: str
    original_name: str
    text: str
    normalized_text: str
    unresolved: tuple[UnresolvedFragment, ...] = ()
    review: ReviewState


class CorpusDetail(CorpusSummary):
    """The review table: the summary and every line."""

    lines: tuple[CorpusLine, ...] = ()


class CorpusList(ContractModel):
    corpora: tuple[CorpusSummary, ...] = ()


class CorpusCreation(ContractModel):
    """A new corpus: uploaded recordings with a source declaration, or the Edge test teacher."""

    slug: str
    source: Optional[str] = None
    # The administrator confirmed the recordings are theirs or authorised in writing.
    consent: bool = False


class LineUpload(ContractModel):
    """The fields sent with one uploaded recording (the audio is the body)."""

    slug: str
    # The client's file name: display text and format hint only, never a path.
    filename: str = Field(default="", max_length=1024)
    text: str = ""


class LineAdded(ContractModel):
    line: CorpusLine
    duration: float


class LineEdit(ContractModel):
    """A new transcript (the line goes back to pending) and/or a review state."""

    slug: str
    line_id: str
    text: Optional[str] = None
    review: Optional[ReviewState] = None


class LineEdited(ContractModel):
    line: CorpusLine
    summary: CorpusSummary


class TranscriptFile(ContractModel):
    """An uploaded same-name ``.txt`` file or ``metadata.csv``; base64 in JSON."""

    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")

    name: str
    content: bytes


class TranscriptImport(ContractModel):
    slug: str
    files: tuple[TranscriptFile, ...]


class TranscriptsApplied(ContractModel):
    applied: int
    without_transcript: tuple[str, ...] = ()


class LineConfirmation(ContractModel):
    """Confirm every pending line with a transcript, or only ``line_ids``."""

    slug: str
    line_ids: Optional[tuple[str, ...]] = None


class LinesConfirmed(ContractModel):
    confirmed: int
    without_text: int
    summary: CorpusSummary


class ClauseAcknowledgement(ContractModel):
    """The Microsoft clause text the console showed and the administrator confirmed."""

    slug: str
    shown_text: str


class ClauseAcknowledged(ContractModel):
    acknowledged_at: str
    clause_reference: str
    clause_effective: str


class TranscriptionStart(ContractModel):
    slug: str
    line_ids: Optional[tuple[str, ...]] = None
    model: str = DEFAULT_TRANSCRIPTION_MODEL
    # Set by the core when its own state rules the GPU out (a connected stage);
    # otherwise the layer decides by free VRAM.
    cpu_reason: Optional[str] = None


class FailedTranscription(ContractModel):
    line_id: str
    message: str


class TranscriptionProgress(ContractModel):
    """The automatic transcription job of a corpus; ``idle`` when it has none."""

    state: Literal["idle", "running", "done", "cancelled", "failed"]
    slug: Optional[str] = None
    model: Optional[str] = None
    total: int = 0
    done: int = 0
    skipped: int = 0
    failed: tuple[FailedTranscription, ...] = ()
    message: str = ""
    cancel_requested: bool = False
    device: Optional[TranscriptionDevice] = None
    fallback_reason: Optional[str] = None


class TrainingCheck(ContractModel):
    """One named reason a training job may or may not start; ``detail`` has the numbers."""

    id: str
    label: str
    status: CheckStatus
    reason: str
    detail: dict[str, Any] = Field(default_factory=dict)


class TrainingPreflight(ContractModel):
    can_start: bool
    checks: tuple[TrainingCheck, ...] = ()


class TrainingStage(ContractModel):
    id: str
    label: str
    status: str
    detail: str = ""
    progress: float = 0.0
    seconds: Optional[float] = None


class TrainingJob(ContractModel):
    """A training job (訓練工作): from a corpus to a voice model in the catalog."""

    id: str
    corpus: str
    name: str
    voice_id: str
    usage: str
    source: str
    status: Literal["running", "cancelling", "done", "failed", "cancelled"]
    stage: Optional[str] = None
    stages: tuple[TrainingStage, ...] = ()
    progress: int
    message: str = ""
    error: str = ""
    started_at: float
    finished_at: Optional[float] = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    log_lines: int = 0


class TrainingJobState(ContractModel):
    """The running job, else the latest finished one; ``None`` when there is none."""

    job: Optional[TrainingJob] = None


class EdgeClause(ContractModel):
    """The Microsoft clause the console shows and sends back verbatim."""

    reference: str
    effective: str
    text: str


class TrainingSettings(ContractModel):
    min_free_vram_gb: float
    whisper_model: str
    edge_clause: EdgeClause


class TrainingQuery(ContractModel):
    corpus: Optional[str] = None
    name: Optional[str] = None


class TrainingStatus(ContractModel):
    """The job, the layer's pre-flight checks and the settings the console shows."""

    job: Optional[TrainingJob] = None
    preflight: TrainingPreflight
    settings: TrainingSettings


class TrainingStart(ContractModel):
    """Start a job; an Edge corpus also names a voice and a preset or its own text list."""

    corpus: str
    name: str
    voice: Optional[str] = None
    preset: Optional[str] = None
    sentences: Optional[str] = None


class TrainingLogQuery(ContractModel):
    offset: int = Field(default=0, ge=0)


class TrainingLog(ContractModel):
    """Log lines from absolute line ``start``; ``next`` is where the following page starts."""

    job_id: Optional[str] = None
    start: int
    lines: tuple[str, ...] = ()
    next: int
    total: int


class TrainingActivity(ContractModel):
    """Whether a training job holds the GPU; the core refuses new stages meanwhile."""

    active: bool


class TextListReview(ContractModel):
    """An administrator's text list for an Edge corpus, one sentence per line."""

    sentences: str


class ReviewedSentence(ContractModel):
    index: int
    text: str
    spoken: str
    unresolved: tuple[UnresolvedFragment, ...] = ()


class TextReview(ContractModel):
    ok: bool
    total: int
    unresolved_count: int
    estimated_seconds: float
    sentences: tuple[ReviewedSentence, ...] = ()


@runtime_checkable
class VoiceTraining(Protocol):
    """The voice-training operations of ``TtsService``.

    Refusals raise ``TtsError`` with the HTTP status; ``extra`` carries
    ``preflight`` (a refused start), ``unresolved`` (digits in a text list) or
    ``problems`` (transcript files).
    """

    def list_corpora(self) -> CorpusList:
        """``GET /training/corpora``."""
        ...

    def create_corpus(self, request: CorpusCreation) -> CorpusSummary:
        """``POST /training/corpora``."""
        ...

    def get_corpus(self, ref: CorpusRef) -> CorpusDetail:
        """``GET /training/corpus``: the review table."""
        ...

    def add_line(self, audio: bytes, upload: LineUpload) -> LineAdded:
        """``POST /training/lines``: convert, check and store one recording as a pending line."""
        ...

    def edit_line(self, request: LineEdit) -> LineEdited:
        """``PUT /training/lines``."""
        ...

    def line_audio(self, ref: LineRef) -> bytes:
        """``GET /training/lines/audio``: an uploaded line's stored WAV; never Edge output."""
        ...

    def import_transcripts(self, request: TranscriptImport) -> TranscriptsApplied:
        """``POST /training/transcripts``: all or nothing, every problem reported."""
        ...

    def confirm_lines(self, request: LineConfirmation) -> LinesConfirmed:
        """``POST /training/confirm``."""
        ...

    def acknowledge_clause(self, request: ClauseAcknowledgement) -> ClauseAcknowledged:
        """``POST /training/acknowledgement``: record the Edge clause confirmation."""
        ...

    def start_transcription(self, request: TranscriptionStart) -> TranscriptionProgress:
        """``POST /training/transcription``: runs on the layer's worker thread."""
        ...

    def transcription_status(self, ref: CorpusRef) -> TranscriptionProgress:
        """``GET /training/transcription``."""
        ...

    def cancel_transcription(self, ref: CorpusRef) -> TranscriptionProgress:
        """``DELETE /training/transcription``: stop after the current file."""
        ...

    def training_status(self, query: TrainingQuery) -> TrainingStatus:
        """``GET /training/job``: blocking (``nvidia-smi``)."""
        ...

    def start_training(self, request: TrainingStart) -> TrainingJob:
        """``POST /training/job``: the layer's checks, then the job's worker thread."""
        ...

    def cancel_training(self) -> TrainingJobState:
        """``DELETE /training/job``: SIGTERM, then SIGKILL; the corpus is kept."""
        ...

    def training_log(self, query: TrainingLogQuery) -> TrainingLog:
        """``GET /training/log``."""
        ...

    def training_activity(self) -> TrainingActivity:
        """``GET /training/activity``: cheap; asked on every stage offer."""
        ...

    def review_text_list(self, request: TextListReview) -> TextReview:
        """``POST /training/text-review``: pure; touches no disk, network or model."""
        ...


_LINE_AUDIO = ("audio/wav", "audio/mpeg", "audio/flac", "audio/ogg", "audio/mp4", "audio/webm")

TRAINING_OPERATIONS: tuple[HttpOperation, ...] = (
    HttpOperation("GET", "/training/corpora", "list_corpora", "Every corpus with its summary",
                  response=JsonBody(CorpusList)),
    HttpOperation("POST", "/training/corpora", "create_corpus", "Create a corpus with its source",
                  request=JsonBody(CorpusCreation), response=JsonBody(CorpusSummary)),
    HttpOperation("GET", "/training/corpus", "get_corpus", "A corpus's review table",
                  query=CorpusRef, response=JsonBody(CorpusDetail)),
    HttpOperation("POST", "/training/lines", "add_line", "Add one recording as a pending line",
                  query=LineUpload,
                  request=BinaryBody(("application/octet-stream",),
                                     f"WAV, MP3, FLAC, OGG, M4A or WebM; at most {MAX_CORPUS_UPLOAD_BYTES} bytes"),
                  response=JsonBody(LineAdded)),
    HttpOperation("PUT", "/training/lines", "edit_line", "Change a line's transcript or review state",
                  request=JsonBody(LineEdit), response=JsonBody(LineEdited)),
    HttpOperation("GET", "/training/lines/audio", "line_audio", "An uploaded line's stored audio",
                  query=LineRef, response=BinaryBody(_LINE_AUDIO, "The stored recording")),
    HttpOperation("POST", "/training/transcripts", "import_transcripts",
                  "Import same-name .txt files and/or one metadata.csv",
                  request=JsonBody(TranscriptImport), response=JsonBody(TranscriptsApplied)),
    HttpOperation("POST", "/training/confirm", "confirm_lines", "Confirm pending lines with text",
                  request=JsonBody(LineConfirmation), response=JsonBody(LinesConfirmed)),
    HttpOperation("POST", "/training/acknowledgement", "acknowledge_clause",
                  "Record the Edge clause confirmation",
                  request=JsonBody(ClauseAcknowledgement), response=JsonBody(ClauseAcknowledged)),
    HttpOperation("POST", "/training/transcription", "start_transcription",
                  "Transcribe the lines without a transcript",
                  request=JsonBody(TranscriptionStart), response=JsonBody(TranscriptionProgress)),
    HttpOperation("GET", "/training/transcription", "transcription_status",
                  "The corpus's transcription job", query=CorpusRef,
                  response=JsonBody(TranscriptionProgress)),
    HttpOperation("DELETE", "/training/transcription", "cancel_transcription",
                  "Stop the transcription after the current file", query=CorpusRef,
                  response=JsonBody(TranscriptionProgress)),
    HttpOperation("GET", "/training/job", "training_status",
                  "The job, the layer's pre-flight checks and settings", query=TrainingQuery,
                  response=JsonBody(TrainingStatus)),
    HttpOperation("POST", "/training/job", "start_training", "Check, then start a training job",
                  request=JsonBody(TrainingStart), response=JsonBody(TrainingJob)),
    HttpOperation("DELETE", "/training/job", "cancel_training", "Cancel the running job",
                  response=JsonBody(TrainingJobState)),
    HttpOperation("GET", "/training/log", "training_log", "Job log lines from an offset",
                  query=TrainingLogQuery, response=JsonBody(TrainingLog)),
    HttpOperation("GET", "/training/activity", "training_activity",
                  "Whether a training job holds the GPU", response=JsonBody(TrainingActivity)),
    HttpOperation("POST", "/training/text-review", "review_text_list",
                  "How an Edge text list would be read, sentence by sentence",
                  request=JsonBody(TextListReview), response=JsonBody(TextReview)),
)


# ------------------------------------------------------------------ the service


@runtime_checkable
class TtsService(VoiceTraining, Protocol):
    """The TTS layer as the core sees it; each method is one HTTP operation."""

    def health(self) -> ServiceHealth:
        """``GET /health``."""
        ...

    def apply_engine(self, settings: TtsEngineSettings) -> TtsEngineSettings:
        """``PUT /engine``: the settings every voice shares."""
        ...

    def catalog(self) -> TtsCatalog:
        """``GET /catalog``: reference recordings, models and voice models."""
        ...

    def server_status(self, voice: TtsVoice) -> VoiceServerStatus:
        """``POST /voices/server-status``: is the voice's BreezyVoice server up?"""
        ...

    def prepare_voice(self, request: VoicePreparation) -> TtsVoice:
        """``POST /voices/prepare``: start or warm what the voice needs.

        Returns the voice with its server address resolved; raises ``TtsError``
        when the voice cannot speak.
        """
        ...

    def synthesize(self, request: SynthesisRequest) -> Iterator[bytes]:
        """``POST /synthesize``: the fragment as 16 kHz s16le PCM chunks.

        Closing the iterator cancels the synthesis.
        """
        ...

    def list_voices(self) -> VoiceList:
        """``GET /voices``."""
        ...

    def voice_audio(self, ref: VoiceRef) -> bytes:
        """``GET /voices/audio``: a library voice's stored WAV."""
        ...

    def add_voice(self, audio: bytes, upload: VoiceUpload) -> LibraryVoice:
        """``POST /voices``: validate, convert and store a reference recording."""
        ...

    def delete_voice(self, ref: VoiceRef) -> None:
        """``DELETE /voices``: move a voice to the library's recycle bin.

        Whether a role still uses it is the core's question, asked first.
        """
        ...

    def preview_voice_model(self, request: VoiceModelPreview) -> bytes:
        """``POST /voice-models/preview``: a short WAV; times out on its own."""
        ...


HTTP_API = HttpApi(
    title="Nova Avatar TTS service",
    description=("Loopback speech synthesis, voice library and voice training. "
                 "The core cancels a request by closing its connection."),
    service=TtsService,
    operations=(
        health_operation(),
        engine_operation(TtsEngineSettings),
        HttpOperation("GET", "/catalog", "catalog", "What a role's voice is chosen from",
                      response=JsonBody(TtsCatalog)),
        HttpOperation("POST", "/voices/server-status", "server_status",
                      "Whether the voice's BreezyVoice server answers now",
                      request=JsonBody(TtsVoice), response=JsonBody(VoiceServerStatus)),
        HttpOperation("POST", "/voices/prepare", "prepare_voice",
                      "Start the voice's server or warm its connection",
                      request=JsonBody(VoicePreparation), response=JsonBody(TtsVoice)),
        HttpOperation("POST", "/synthesize", "synthesize", "Synthesize one playable fragment",
                      request=JsonBody(SynthesisRequest),
                      response=BinaryBody((PCM_MEDIA_TYPE,),
                                          "Chunked 16 kHz mono s16le PCM of the fragment")),
        HttpOperation("GET", "/voices", "list_voices", "The voice library",
                      response=JsonBody(VoiceList)),
        HttpOperation("GET", "/voices/audio", "voice_audio", "A library voice's stored recording",
                      query=VoiceRef, response=BinaryBody(("audio/wav",), "Mono PCM16 WAV")),
        HttpOperation("POST", "/voices", "add_voice", "Add a reference recording",
                      query=VoiceUpload,
                      request=BinaryBody(("application/octet-stream",),
                                         "WAV, MP3, FLAC, OGG, M4A or WebM; at most "
                                         f"{MAX_VOICE_UPLOAD_BYTES} bytes"),
                      response=JsonBody(LibraryVoice)),
        HttpOperation("DELETE", "/voices", "delete_voice", "Move a voice to the recycle bin",
                      query=VoiceRef),
        HttpOperation("POST", "/voice-models/preview", "preview_voice_model",
                      "A preset sentence in a voice model's voice",
                      request=JsonBody(VoiceModelPreview),
                      response=BinaryBody(("audio/wav",), "Mono PCM16 WAV")),
        *TRAINING_OPERATIONS,
    ),
)


# ------------------------------------------------------------------ in-process only


class AudioSink(Protocol):
    """Where an in-process TTS engine hands off speech; the core implements it.

    The core forwards PCM to the avatar renderer; the TTS layer never sees the
    renderer or the voice session.
    """

    def put_audio_frame(self, samples: "np.ndarray", eventpoint: dict) -> bool:
        """Accept one 20 ms 16 kHz float32 frame; may block for backpressure."""
        ...

    def accepts_media(self, eventpoint: dict, stage: str) -> bool:
        """Whether media tagged with this envelope still belongs to the turn."""
        ...

    def fragment_playback_committed(self, eventpoint: dict) -> bool:
        """Whether the fragment's audio has started playing to the visitor."""
        ...

    def fragment_playback_ended(self, eventpoint: dict) -> bool:
        """Whether the fragment has finished playing (or no longer matters)."""
        ...

    def notify_fragment_synthesis_failed(self, eventpoint: dict, reason: str) -> None:
        """Report a terminal synthesis failure before any of its audio."""
        ...

    def observe_tts_onset_preroll_ms(self, milliseconds: float) -> None: ...

    def observe_tts_retry(self, *, after_commit: bool) -> None: ...

    def mark_stage_end(self, stage: str) -> None:
        """Record a first-audio latency stage (``tts_first_pcm`` and so on)."""
        ...


class SpeechChannel(Protocol):
    """One session's synthesis worker, feeding the core's ``AudioSink``.

    In-process only. Fragments queue in order; the worker thread synthesizes
    them and hands every frame to the sink. Over loopback HTTP the core would
    implement this itself with one ``synthesize`` request per fragment.
    """

    @property
    def voice(self) -> TtsVoice:
        """The voice the next fragment is spoken with."""
        ...

    def set_voice(self, voice: TtsVoice) -> None:
        """Speak the following fragments with ``voice``."""
        ...

    def speak(self, text: str, eventpoint: dict) -> None:
        """Queue one fragment; ``eventpoint`` carries its turn envelope."""
        ...

    def flush(self) -> None:
        """Barge-in: drop queued and in-flight fragments of the old turn."""
        ...

    def has_pending_work(self) -> bool:
        """Whether text is queued or being synthesized."""
        ...

    def run(self, quit_event: Any) -> None:
        """Start the worker thread; it stops when ``quit_event`` is set."""
        ...


class TtsRuntime(Protocol):
    """What the core needs from an in-process TTS beyond ``TtsService``."""

    def open_channel(self, voice: TtsVoice, sink: AudioSink) -> SpeechChannel:
        """A new channel speaking ``voice`` into ``sink``."""
        ...

    def start(self) -> None:
        """At server startup: recover what a previous process left behind."""
        ...

    def close(self, *, force: bool = False) -> None:
        """At server shutdown: stop jobs, owned servers and shared connections.

        ``force``: the process exits right now; only stop the owned child
        servers that would outlive it, without waiting for anything else.
        """
        ...


__all__ = [
    "DEFAULT_TRANSCRIPTION_MODEL",
    "HTTP_API",
    "MAX_CORPUS_UPLOAD_BYTES",
    "MAX_TRANSCRIPT_FILE_BYTES",
    "MAX_TRANSCRIPT_TEXT_CHARS",
    "MAX_VOICE_UPLOAD_BYTES",
    "PCM_MEDIA_TYPE",
    "TRAINING_OPERATIONS",
    "AudioSink",
    "CheckStatus",
    "ClauseAcknowledged",
    "ClauseAcknowledgement",
    "CorpusCounts",
    "CorpusCreation",
    "CorpusDetail",
    "CorpusLine",
    "CorpusList",
    "CorpusRef",
    "CorpusSummary",
    "EdgeClause",
    "FailedTranscription",
    "FragmentEnvelope",
    "LibraryVoice",
    "LineAdded",
    "LineConfirmation",
    "LineEdit",
    "LineEdited",
    "LineRef",
    "LineUpload",
    "LinesConfirmed",
    "PlayableFragment",
    "PreviewSentence",
    "ReviewState",
    "ReviewedSentence",
    "SpeechChannel",
    "SynthesisRequest",
    "TextListReview",
    "TextReview",
    "TrainingActivity",
    "TrainingCheck",
    "TrainingJob",
    "TrainingJobState",
    "TrainingLog",
    "TrainingLogQuery",
    "TrainingPreflight",
    "TrainingQuery",
    "TrainingSettings",
    "TrainingStage",
    "TrainingStart",
    "TrainingStatus",
    "TranscriptFile",
    "TranscriptImport",
    "TranscriptionDevice",
    "TranscriptionProgress",
    "TranscriptionStart",
    "TranscriptsApplied",
    "TtsCatalog",
    "TtsEngine",
    "TtsEngineSettings",
    "TtsError",
    "TtsModel",
    "TtsRuntime",
    "TtsService",
    "TtsVoice",
    "UnresolvedFragment",
    "VoiceList",
    "VoiceModelInfo",
    "VoiceModelPreview",
    "VoicePreparation",
    "VoiceRef",
    "VoiceServerStatus",
    "VoiceTraining",
    "VoiceUpload",
    "strip_visual_markup",
]
