# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Content-free circuit breaker for the reply streaming pipeline."""
from __future__ import annotations

import time
from collections import deque
from typing import Callable


class ReplyCircuitBreaker:
    """Open after three recent failed turns and affect only later turns."""

    def __init__(
        self,
        *,
        threshold: int = 3,
        window_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = threshold
        self._window_seconds = window_seconds
        self._clock = clock
        self._errors: deque[float] = deque()
        self._open = False
        self._active_mode = "streaming"

    def mode_for_next_turn(self) -> str:
        self._prune()
        self._active_mode = "legacy" if self._open else "streaming"
        return self._active_mode

    def mode_for_active_turn(self) -> str:
        return self._active_mode

    def record_pipeline_error(self) -> bool:
        """Return True only when this error newly opens the breaker."""
        self._prune()
        self._errors.append(self._clock())
        opened = not self._open and len(self._errors) >= self._threshold
        if opened:
            self._open = True
        return opened

    def record_turn_success(self) -> None:
        """A successful streaming turn breaks the consecutive error streak."""
        if not self._open:
            self._errors.clear()

    def record_health_probe(self, healthy: bool) -> bool:
        if not healthy:
            return False
        self._open = False
        self._errors.clear()
        return True

    @property
    def is_open(self) -> bool:
        return self._open

    def _prune(self) -> None:
        cutoff = self._clock() - self._window_seconds
        while self._errors and self._errors[0] < cutoff:
            self._errors.popleft()
