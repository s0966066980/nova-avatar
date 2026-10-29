# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Content-free, monotonic measurements for one voice turn."""
from __future__ import annotations

import time
import math
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterator, Optional


Clock = Callable[[], float]
StageObserver = Callable[[str, float], None]

# Stage durations are measured where the work runs; durations, not clocks,
# cross threads. ``pre_answer`` runs from the transcript to the main answer
# (or fixed reply) that is played and contains ``retrieval``. ``routing`` runs
# concurrently with it; ``routing_hold`` is how long synthesized answer audio
# waited for the routing decision, inside ``avatar_to_webrtc_commit``.
# ``model_info`` is the llama-server preflight inside ``llm_first_token``.
#
# Before the speech end (not part of ``first_audio_seconds``):
# ``vad_endpoint`` is the silence wait on the audio timeline (the configured
# ``min_silence_ms`` rounded up to whole VAD frames, not a wall-clock reading);
# ``vad_speech_tail`` is how long the VAD still judged speech after the voice
# fell below -40 dBFS; ``vad_processing`` runs from the arrival of the uplink
# frame that completed the endpoint to the endpoint decision.
# After the first audio: ``webrtc_audible_onset`` runs from the first nonzero
# reply frame sent to the first one whose peak exceeds ``AUDIBLE_PEAK``.
STAGE_NAMES = (
    "vad_endpoint",
    "vad_speech_tail",
    "vad_processing",
    "asr",
    "pre_answer",
    "routing",
    "retrieval",
    "routing_hold",
    "model_info",
    "llm_first_token",
    "llm_first_speech",
    "llm_total",
    "first_fragment",
    "tts_first_encoded",
    "tts_pcm_available",
    "tts_first_pcm",
    "musetalk_first_batch",
    "musetalk_inference_first_result",
    "avatar_pasteback_done",
    "webrtc_audio_enqueue",
    "webrtc_video_enqueue",
    "avatar_to_webrtc_commit",
    "webrtc_audio_commit",
    "webrtc_audible_onset",
)

# int16 peak of a 20 ms frame above which reply audio is audible (-54 dBFS).
# The harness applies the same threshold to the frames it decodes.
AUDIBLE_PEAK = 64

# Stages a main answer owns. A discarded speculative answer forgets them so the
# reply that is actually played measures its own.
ANSWER_STAGES = STAGE_NAMES[STAGE_NAMES.index("model_info"):]


_stage_observer: ContextVar[Optional[StageObserver]] = ContextVar(
    "turn_stage_observer", default=None,
)


@contextmanager
def observe_stages(observer: StageObserver) -> Iterator[None]:
    """Route ``timed_stage`` durations in this context to ``observer``."""
    token = _stage_observer.set(observer)
    try:
        yield
    finally:
        _stage_observer.reset(token)


@contextmanager
def timed_stage(stage: str, *, clock: Clock = time.monotonic) -> Iterator[None]:
    """Time a block for the current turn, if one is observing this context."""
    TurnMetrics._validate_stage(stage)
    observer = _stage_observer.get()
    started = clock()
    try:
        yield
    finally:
        if observer is not None:
            observer(stage, max(0.0, clock() - started))


def _duration(start: Optional[float], end: Optional[float]) -> Optional[float]:
    if start is None or end is None:
        return None
    return round(max(0.0, end - start), 6)


def _mark(at: Optional[float]) -> Optional[float]:
    return None if at is None else round(at, 6)


class TurnMetrics:
    """Collect the fixed, privacy-safe measurements for a single turn.

    The API deliberately has no arbitrary payload or content field. This keeps
    transcripts, generated text, and audio out of the baseline telemetry path.
    """

    def __init__(self, turn_id: str, *, clock: Clock = time.monotonic) -> None:
        self._turn_id = turn_id
        self._clock = clock
        self._speech_end_at: Optional[float] = None
        self._prompt_accepted_at: Optional[float] = None
        self._first_audio_at: Optional[float] = None
        self._first_audible_at: Optional[float] = None
        self._interrupt_at: Optional[float] = None
        self._output_stopped_at: Optional[float] = None
        self._listening_resumed_at: Optional[float] = None
        self._max_media_debt_seconds = 0.0
        self._max_abs_av_offset_seconds = 0.0
        self._stale_drops: Counter[str] = Counter()
        self._max_audio_pacing_lag_ms = 0.0
        self._audio_pacing_rebase_count = 0
        self._min_audio_release_interval_ms: Optional[float] = None
        self._audio_catch_up_burst_count = 0
        self._max_tts_onset_preroll_ms = 0.0
        self._tts_retry_after_pcm_count = 0
        self._tts_retry_after_playback_commit_count = 0
        self._stage_started_at: dict[str, float] = {}
        self._stage_finished_at: dict[str, float] = {}
        self._stage_durations: dict[str, float] = {}

    def mark_speech_end(self) -> None:
        if self._speech_end_at is None:
            self._speech_end_at = self._clock()

    def mark_prompt_accepted(self) -> None:
        """The transcript or typed prompt enters the reply pipeline."""
        if self._prompt_accepted_at is None:
            self._prompt_accepted_at = self._clock()

    def mark_first_audio(self) -> None:
        if self._first_audio_at is None:
            self._first_audio_at = self._clock()

    def mark_first_audible(self) -> None:
        """The first reply frame above ``AUDIBLE_PEAK`` is sent."""
        if self._first_audible_at is None:
            self._first_audible_at = self._clock()

    def mark_interrupt(self) -> None:
        if self._interrupt_at is None:
            self._interrupt_at = self._clock()

    def mark_output_stopped(self) -> None:
        if self._interrupt_at is not None and self._output_stopped_at is None:
            self._output_stopped_at = self._clock()

    def mark_listening_resumed(self) -> None:
        if self._listening_resumed_at is None:
            self._listening_resumed_at = self._clock()

    def mark_stage_start(self, stage: str) -> None:
        """Record the first start time for a fixed, privacy-safe stage."""
        self._validate_stage(stage)
        if stage not in self._stage_started_at:
            self._stage_started_at[stage] = self._clock()

    def mark_stage_end(self, stage: str) -> None:
        """Record the first completion time for a fixed stage."""
        self._validate_stage(stage)
        if stage not in self._stage_finished_at:
            self._stage_finished_at[stage] = self._clock()

    def record_stage_duration(self, stage: str, seconds: float) -> None:
        """Record a measured audio-timeline interval without inventing clocks."""
        self._validate_stage(stage)
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("stage duration must be finite and nonnegative")
        self._stage_durations.setdefault(stage, round(float(seconds), 6))

    def discard_answer_stages(self) -> None:
        """Forget a discarded answer's stages and reopen ``pre_answer``."""
        for stage in ANSWER_STAGES:
            self._stage_started_at.pop(stage, None)
            self._stage_finished_at.pop(stage, None)
            self._stage_durations.pop(stage, None)
        self._stage_finished_at.pop("pre_answer", None)
        self._stage_durations.pop("pre_answer", None)

    @staticmethod
    def _validate_stage(stage: str) -> None:
        if stage not in STAGE_NAMES:
            raise ValueError(f"unsupported latency stage: {stage}")

    def observe_media_debt(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("media debt cannot be negative")
        self._max_media_debt_seconds = max(self._max_media_debt_seconds, seconds)

    def observe_av_offset(self, seconds: float) -> None:
        self._max_abs_av_offset_seconds = max(
            self._max_abs_av_offset_seconds,
            abs(seconds),
        )

    def record_stale_drop(self, stage: str, reason: str) -> None:
        if not stage or not reason:
            raise ValueError("stale drop stage and reason are required")
        self._stale_drops[f"{stage}:{reason}"] += 1

    def observe_audio_pacing(
        self,
        *,
        lag_seconds: float = 0.0,
        rebase_count: int = 0,
        min_release_interval_seconds: Optional[float] = None,
        catch_up_burst_count: int = 0,
    ) -> None:
        self._max_audio_pacing_lag_ms = max(
            self._max_audio_pacing_lag_ms,
            round(max(0.0, lag_seconds) * 1000.0, 3),
        )
        self._audio_pacing_rebase_count = max(
            self._audio_pacing_rebase_count,
            int(rebase_count),
        )
        if min_release_interval_seconds is not None:
            interval_ms = round(max(0.0, min_release_interval_seconds) * 1000.0, 3)
            if (
                self._min_audio_release_interval_ms is None
                or interval_ms < self._min_audio_release_interval_ms
            ):
                self._min_audio_release_interval_ms = interval_ms
        self._audio_catch_up_burst_count = max(
            self._audio_catch_up_burst_count,
            int(catch_up_burst_count),
        )

    def observe_tts_onset_preroll_ms(self, milliseconds: float) -> None:
        if milliseconds < 0:
            raise ValueError("onset preroll cannot be negative")
        self._max_tts_onset_preroll_ms = max(
            self._max_tts_onset_preroll_ms,
            round(milliseconds, 3),
        )

    def observe_tts_retry(self, *, after_commit: bool) -> None:
        if after_commit:
            self._tts_retry_after_playback_commit_count += 1
        else:
            self._tts_retry_after_pcm_count += 1

    def snapshot(self) -> dict:
        """Return scalar metadata suitable for logs and SLO aggregation."""
        return {
            "turn_id": self._turn_id,
            "first_audio_seconds": _duration(
                self._speech_end_at,
                self._first_audio_at,
            ),
            "prompt_first_audio_seconds": _duration(
                self._prompt_accepted_at,
                self._first_audio_at,
            ),
            "interrupt_stop_seconds": _duration(
                self._interrupt_at,
                self._output_stopped_at,
            ),
            "listening_resume_seconds": _duration(
                self._interrupt_at,
                self._listening_resumed_at,
            ),
            "max_media_debt_seconds": round(self._max_media_debt_seconds, 6),
            "max_abs_av_offset_seconds": round(
                self._max_abs_av_offset_seconds,
                6,
            ),
            "stale_drops": dict(sorted(self._stale_drops.items())),
            "audio_pacing_lag_ms": round(self._max_audio_pacing_lag_ms, 3),
            "audio_pacing_rebase_count": self._audio_pacing_rebase_count,
            "audio_release_interval_ms": self._min_audio_release_interval_ms,
            "audio_catch_up_burst_count": self._audio_catch_up_burst_count,
            "tts_onset_preroll_ms": round(self._max_tts_onset_preroll_ms, 3),
            "tts_retry_after_pcm_count": self._tts_retry_after_pcm_count,
            "tts_retry_after_playback_commit_count": (
                self._tts_retry_after_playback_commit_count
            ),
            # Raw session-clock readings (time.monotonic in production). Only a
            # client on the same host, such as the loopback stage harness, can
            # compare them with its own clock to split the client offset.
            "clock_marks": {
                "speech_end": _mark(self._speech_end_at),
                "first_audio": _mark(self._first_audio_at),
                "first_audible": _mark(self._first_audible_at),
            },
            "stage_seconds": {
                stage: self._stage_durations.get(stage, _duration(
                    self._stage_started_at.get(stage),
                    self._stage_finished_at.get(stage),
                ))
                for stage in STAGE_NAMES
            },
        }
