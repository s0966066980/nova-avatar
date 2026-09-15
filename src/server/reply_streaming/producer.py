# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Cooperative LLM-token producer for the bounded TTS fragment channel."""
from __future__ import annotations

from enum import Enum
from typing import AsyncIterable, Callable

from .channel import (
    BackpressureTruncated,
    BoundedFragmentChannel,
    FragmentChannelClosed,
    PlayableFragment,
)
from .fragmenter import SemanticFragmenter
from .turn import TurnContext


class ProducerResult(str, Enum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    TRUNCATED = "truncated"


def estimate_speech_seconds(text: str) -> float:
    """Conservative pre-TTS duration estimate for Mandarin-oriented replies."""
    content_chars = sum(character.isalnum() for character in text)
    return round(max(0.2, content_chars / 8.0), 6)


class ReplyFragmentProducer:
    """Convert async LLM tokens to fenced, media-budgeted TTS fragments."""

    def __init__(
        self,
        turn: TurnContext,
        channel: BoundedFragmentChannel,
        *,
        fragmenter: SemanticFragmenter | None = None,
        estimate_seconds: Callable[[str], float] = estimate_speech_seconds,
    ) -> None:
        self._turn = turn
        self._channel = channel
        self._fragmenter = fragmenter or SemanticFragmenter()
        self._estimate_seconds = estimate_seconds
        self._sequence = 0

    async def run(self, tokens: AsyncIterable[str]) -> ProducerResult:
        async for token in tokens:
            if self._turn.cancelled.is_set() or self._turn.terminal:
                return ProducerResult.CANCELLED
            result = await self._emit(self._fragmenter.feed(token))
            if result is not None:
                return result
        if self._turn.cancelled.is_set() or self._turn.terminal:
            return ProducerResult.CANCELLED
        result = await self._emit(self._fragmenter.flush())
        return result or ProducerResult.COMPLETED

    async def _emit(self, texts: list[str]) -> ProducerResult | None:
        for text in texts:
            envelope = self._turn.envelope(
                stage="tts_fragment",
                sequence=self._sequence,
            )
            if not self._turn.accepts(envelope):
                return ProducerResult.CANCELLED
            fragment = PlayableFragment(
                envelope=envelope,
                text=text,
                estimated_seconds=self._estimate_seconds(text),
            )
            try:
                await self._channel.put(fragment)
            except BackpressureTruncated:
                return ProducerResult.TRUNCATED
            except FragmentChannelClosed:
                return ProducerResult.CANCELLED
            self._sequence += 1
        return None
