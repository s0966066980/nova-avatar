# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Time a block of work for whoever observes the current context.

A processing layer times its own work with ``timed_stage``; the core decides
whether anyone listens with ``observe_stages`` and owns the stage vocabulary,
so an unknown name is rejected where the duration is recorded. Durations, not
clocks, cross threads.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterator, Optional

Clock = Callable[[], float]
StageObserver = Callable[[str, float], None]

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
    observer = _stage_observer.get()
    started = clock()
    try:
        yield
    finally:
        if observer is not None:
            observer(stage, max(0.0, clock() - started))
