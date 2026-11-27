# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Text-to-speech. Transport when split: one request per fragment, chunked PCM back.

The core owns turns and fragment order. The engine reports PCM frames and
fragment events to an ``AudioSink`` and never learns who renders them.
"""
from __future__ import annotations

from typing import Any, Iterator, Protocol

from pydantic import BaseModel


class SynthesizeRequest(BaseModel):
    text: str
    turn_id: str = ""
    generation: int = 0
    fragment_sequence: int = 0


class AudioSink(Protocol):
    """Where an engine hands 20 ms PCM frames and fragment events.

    Only ``put_audio_frame`` is required. An engine looks the optional members
    up with ``getattr`` and skips those a sink does not provide:
    ``mark_stage_end``, ``fragment_playback_ended``, ``fragment_playback_committed``,
    ``discard_uncommitted_fragment``, ``notify_fragment_synthesis_failed``,
    ``observe_tts_onset_preroll_ms``, ``observe_tts_retry``, ``accepts_media``.
    """

    def put_audio_frame(self, samples: Any, eventpoint: dict | None = None) -> Any: ...


class TtsService(Protocol):
    def synthesize(self, request: SynthesizeRequest) -> Iterator[bytes]:
        """Yield PCM (16 kHz, mono, int16) for one fragment; closing it cancels."""

    def flush(self) -> None:
        """Drop queued text and stop the current utterance."""
