# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The ``fake`` TTS engine: silence of a known length, with no model or network.

It exists so the rest of the system can be exercised on a machine without a GPU,
voice models or Edge access (spec decision 15). Its PCM goes through the same
prefetch, ``TurnPCMEmitter`` and ``AudioSink`` path as a real engine, so the
fragment events, the playback fence and cancellation behave identically; only
the samples are zeros.

A fragment lasts as long as the caller asks: ``estimated_seconds`` in its
eventpoint (the adapter's ``synthesize`` passes the fragment's estimate) when it
is positive, otherwise ``SECONDS_PER_CHARACTER`` for each character of text.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

from nova_tts.engines.prefetching import PrefetchingTTS
from nova_tts.pcm_emitter import StreamingSilenceTrimmer, TurnPCMEmitter

# How long the fake takes to "say" one character when no length is requested.
SECONDS_PER_CHARACTER = 0.1


class FakeTTS(PrefetchingTTS):
    """Speaks silence; ``synthesized`` records the texts it was asked to say."""

    LOG_NAME = "fake"

    def __init__(self, config, sink):
        super().__init__(config, sink)
        self.synthesized: list[str] = []

    def _synthesize_fragment(
        self, text: str, textevent: dict, alive: Callable[[], bool] | None = None
    ) -> np.ndarray:
        self.synthesized.append(text)
        requested = textevent.get("estimated_seconds")
        seconds = float(requested) if isinstance(requested, (int, float)) and requested > 0 \
            else len(text) * SECONDS_PER_CHARACTER
        return np.zeros(round(seconds * self.sample_rate), dtype=np.float32)

    def _new_emitter(self, text: str, textevent: dict, current: Callable[[], bool]) -> TurnPCMEmitter:
        # The silence trimmer would drop all of the fragment's samples; keep them
        # so frames, events and the fence are those of a real fragment.
        keep_all = StreamingSilenceTrimmer(self.sample_rate, threshold=-1.0, onset_threshold=-1.0)
        return TurnPCMEmitter(self, text, textevent, chunk_guard=lambda _sequence: current(),
                              trimmer=keep_all)
