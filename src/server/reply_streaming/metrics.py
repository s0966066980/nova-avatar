# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Content-free, monotonic measurements for one voice turn."""
from __future__ import annotations

import time
from collections import Counter
from typing import Callable, Optional


Clock = Callable[[], float]

STAGE_NAMES = (
    "vad_endpoint",
    "asr",
    "llm_first_token",
    "llm_total",
    "first_fragment",
    "tts_first_encoded",
    "tts_first_pcm",
    "musetalk_first_batch",
    "musetalk_inference_first_result",
    "avatar_pasteback_done",
    "webrtc_audio_enqueue",
    "webrtc_video_enqueue",
    "avatar_to_webrtc_commit",
    "webrtc_audio_commit",
)


def _duration(start: Optional[float], end: Optional[float]) -> Optional[float]:
    if start is None or end is None:
        return None
    return round(max(0.0, end - start), 6)


class TurnMetrics:
    """Collect the fixed, privacy-safe measurements for a single turn.

    The API deliberately has no arbitrary payload or content field. This keeps
    transcripts, generated text, and audio out of the baseline telemetry path.
    """

    def __init__(self, turn_id: str, *, clock: Clock = time.monotonic) -> None:
        self._turn_id = turn_id
        self._clock = clock
        self._speech_end_at: Optional[float] = None
        self._first_audio_at: Optional[float] = None
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

    def mark_speech_end(self) -> None:
        if self._speech_end_at is None:
            self._speech_end_at = self._clock()

    def mark_first_audio(self) -> None:
        if self._first_audio_at is None:
            self._first_audio_at = self._clock()

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
            "stage_seconds": {
                stage: _duration(
                    self._stage_started_at.get(stage),
                    self._stage_finished_at.get(stage),
                )
                for stage in STAGE_NAMES
            },
        }
