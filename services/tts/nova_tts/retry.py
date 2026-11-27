# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""A single retry allowance shared by all stages of one reply turn."""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class RetryPermit:
    max_wait_seconds: float


class RetryBudget:
    def __init__(self, *, max_retries: int = 1, extra_wait_seconds: float = 1.0) -> None:
        if max_retries < 0:
            raise ValueError("max retries cannot be negative")
        if extra_wait_seconds < 0:
            raise ValueError("extra wait cannot be negative")
        self._remaining = max_retries
        self._extra_wait_seconds = float(extra_wait_seconds)
        self._lock = Lock()

    def claim_retry(self) -> RetryPermit | None:
        with self._lock:
            if self._remaining <= 0:
                return None
            self._remaining -= 1
            return RetryPermit(max_wait_seconds=self._extra_wait_seconds)
