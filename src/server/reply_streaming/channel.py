# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Media-time bounded channel between LLM fragmentation and TTS."""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass

from .media_debt import MediaDebtBudget
from .turn import TurnEnvelope


class FragmentChannelClosed(RuntimeError):
    pass


class BackpressureTruncated(RuntimeError):
    """The sustained high watermark ended generation at a fragment boundary."""


@dataclass(frozen=True)
class PlayableFragment:
    envelope: TurnEnvelope
    text: str
    estimated_seconds: float

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("fragment text cannot be empty")
        if self.estimated_seconds < 0:
            raise ValueError("estimated duration cannot be negative")

    @property
    def fragment_id(self) -> str:
        return f"{self.envelope.turn_id}:{self.envelope.sequence}"


class BoundedFragmentChannel:
    """FIFO channel whose producer pressure follows unplayed media seconds."""

    def __init__(self, budget: MediaDebtBudget | None = None) -> None:
        self._budget = budget or MediaDebtBudget()
        self._items: deque[PlayableFragment] = deque()
        self._condition = asyncio.Condition()
        self._closed = False

    @property
    def media_debt_seconds(self) -> float:
        return self._budget.seconds

    @property
    def backpressured(self) -> bool:
        return self._budget.backpressured

    @property
    def truncation_requested(self) -> bool:
        return self._budget.truncation_requested

    @property
    def qsize(self) -> int:
        return len(self._items)

    async def put(self, fragment: PlayableFragment) -> None:
        async with self._condition:
            while self._budget.backpressured and not self._closed:
                if self._budget.truncation_requested:
                    raise BackpressureTruncated(
                        "media debt remained above the high watermark"
                    )
                await self._condition.wait()
            if self._closed:
                raise FragmentChannelClosed("fragment channel is closed")
            self._budget.reserve(
                fragment.fragment_id,
                estimated_seconds=fragment.estimated_seconds,
            )
            self._items.append(fragment)
            self._condition.notify_all()

    async def get(self) -> PlayableFragment:
        async with self._condition:
            await self._condition.wait_for(lambda: self._closed or bool(self._items))
            if not self._items:
                raise FragmentChannelClosed("fragment channel is closed")
            return self._items.popleft()

    async def resolve(self, fragment_id: str, *, actual_seconds: float) -> None:
        async with self._condition:
            self._budget.resolve(fragment_id, actual_seconds=actual_seconds)
            self._condition.notify_all()

    async def consume(self, seconds: float) -> None:
        async with self._condition:
            self._budget.consume(seconds)
            self._condition.notify_all()

    async def close(self) -> None:
        async with self._condition:
            self._closed = True
            self._condition.notify_all()
