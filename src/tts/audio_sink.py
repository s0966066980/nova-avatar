# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The narrow interface a TTS engine uses to hand off speech (ADR 0027).

The core implements it and forwards PCM to the avatar renderer; the TTS layer
never sees the renderer or the voice session.
"""
from __future__ import annotations

from typing import Protocol

import numpy as np


class AudioSink(Protocol):
    def put_audio_frame(self, samples: np.ndarray, eventpoint: dict) -> bool:
        """Accept one 20 ms 16 kHz float32 frame; may block for backpressure."""
        ...

    def accepts_media(self, eventpoint: dict, stage: str) -> bool:
        """Whether media tagged with this envelope still belongs to the turn."""
        ...

    def fragment_playback_committed(self, eventpoint: dict) -> bool:
        """Whether the fragment's audio has started playing to the visitor."""
        ...

    def fragment_playback_ended(self, eventpoint: dict) -> bool:
        """Whether the fragment has finished playing (or no longer matters)."""
        ...

    def notify_fragment_synthesis_failed(self, eventpoint: dict, reason: str) -> None:
        """Report a terminal synthesis failure before any of its audio."""
        ...

    def observe_tts_onset_preroll_ms(self, milliseconds: float) -> None: ...

    def observe_tts_retry(self, *, after_commit: bool) -> None: ...

    def mark_stage_end(self, stage: str) -> None:
        """Record a first-audio latency stage (``tts_first_pcm`` and so on)."""
        ...
