# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""A controllable clock for the tests of anything that takes ``clock=``."""
from __future__ import annotations


class FakeClock:
    """Calling it returns the current time; ``advance`` moves it, ``now`` can be set."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds
