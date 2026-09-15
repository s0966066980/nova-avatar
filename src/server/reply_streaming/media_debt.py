# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Media-time accounting used to bound reply-streaming queues."""
from __future__ import annotations

import time
from typing import Callable


class MediaDebtBudget:
    """Track unplayed media seconds with high/low-watermark hysteresis."""

    def __init__(
        self,
        *,
        high_watermark_seconds: float = 2.0,
        low_watermark_seconds: float = 1.0,
        backpressure_timeout_seconds: float = 3.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if low_watermark_seconds < 0:
            raise ValueError("low watermark cannot be negative")
        if high_watermark_seconds <= low_watermark_seconds:
            raise ValueError("high watermark must exceed low watermark")
        if backpressure_timeout_seconds <= 0:
            raise ValueError("backpressure timeout must be positive")
        self._high = float(high_watermark_seconds)
        self._low = float(low_watermark_seconds)
        self._backpressure_timeout = float(backpressure_timeout_seconds)
        self._clock = clock
        self._seconds = 0.0
        self._estimates: dict[str, float] = {}
        self._backpressured = False
        self._backpressure_started_at: float | None = None

    @property
    def seconds(self) -> float:
        return round(self._seconds, 6)

    @property
    def backpressured(self) -> bool:
        return self._backpressured

    @property
    def backpressure_seconds(self) -> float:
        if self._backpressure_started_at is None:
            return 0.0
        return round(max(0.0, self._clock() - self._backpressure_started_at), 6)

    @property
    def truncation_requested(self) -> bool:
        return (
            self._backpressured
            and self.backpressure_seconds >= self._backpressure_timeout
        )

    def reserve(self, fragment_id: str, *, estimated_seconds: float) -> None:
        if not fragment_id:
            raise ValueError("fragment id is required")
        if fragment_id in self._estimates:
            raise ValueError(f"fragment already reserved: {fragment_id}")
        duration = self._duration(estimated_seconds)
        self._estimates[fragment_id] = duration
        self._seconds += duration
        self._update_pressure()

    def resolve(self, fragment_id: str, *, actual_seconds: float) -> None:
        try:
            estimate = self._estimates.pop(fragment_id)
        except KeyError as exc:
            raise KeyError(f"fragment is not reserved: {fragment_id}") from exc
        self._seconds += self._duration(actual_seconds) - estimate
        self._seconds = max(0.0, self._seconds)
        self._update_pressure()

    def consume(self, seconds: float) -> None:
        self._seconds = max(0.0, self._seconds - self._duration(seconds))
        self._update_pressure()

    @staticmethod
    def _duration(seconds: float) -> float:
        duration = float(seconds)
        if duration < 0:
            raise ValueError("media duration cannot be negative")
        return duration

    def _update_pressure(self) -> None:
        normalized_seconds = self.seconds
        if self._backpressured:
            if normalized_seconds <= self._low:
                self._backpressured = False
                self._backpressure_started_at = None
        elif normalized_seconds >= self._high:
            self._backpressured = True
            self._backpressure_started_at = self._clock()
