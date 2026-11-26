# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Speech-synthesis (TTS) layer contract.

Loopback shape (spec decision 7): one request per playable fragment; the PCM
comes back chunked as 16 kHz s16le. In-process, an engine hands each 20 ms
frame to the core's ``AudioSink`` instead.

Ticket 07 step 2 adds ``TtsService``, its DTOs and ``HTTP_API`` here.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic import ConfigDict, Field, field_validator

from nova_contracts.common import ContractModel

if TYPE_CHECKING:  # numpy is the caller's dependency, never this package's.
    import numpy as np


class FragmentEnvelope(ContractModel):
    """The turn identity a fragment carries; built from the core's TurnEnvelope."""

    model_config = ConfigDict(from_attributes=True)

    turn_id: str
    generation: int
    sequence: int


class PlayableFragment(ContractModel):
    """A reply fragment the core cut and the TTS layer synthesizes."""

    envelope: FragmentEnvelope
    text: str
    estimated_seconds: float = Field(ge=0)

    @field_validator("text")
    @classmethod
    def _has_text(cls, text: str) -> str:
        if not text.strip():
            raise ValueError("fragment text cannot be empty")
        return text

    @property
    def fragment_id(self) -> str:
        return f"{self.envelope.turn_id}:{self.envelope.sequence}"


class AudioSink(Protocol):
    """Where an in-process TTS engine hands off speech; the core implements it.

    The core forwards PCM to the avatar renderer; the TTS layer never sees the
    renderer or the voice session.
    """

    def put_audio_frame(self, samples: "np.ndarray", eventpoint: dict) -> bool:
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


__all__ = ["AudioSink", "FragmentEnvelope", "PlayableFragment"]
