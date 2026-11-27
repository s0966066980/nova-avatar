# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The narrow interface a TTS engine uses to hand audio and events to its owner.

The core decides what implements it (today the avatar renderer does); the TTS
layer depends on this protocol and never on the renderer. Only
``put_audio_frame`` is required. Engines look the other members up with
``getattr`` and skip those a sink does not provide, so a minimal sink works.
"""
from __future__ import annotations

from typing import Any, Protocol


class AudioSink(Protocol):
    def put_audio_frame(self, samples: Any, eventpoint: dict | None = None) -> Any:
        """Receive one 20 ms PCM frame and the fragment event that goes with it."""

    # Optional members (looked up with ``getattr``):
    #   mark_stage_end(stage)                      latency stage marks
    #   fragment_playback_ended(eventpoint)        has the fragment finished playing
    #   fragment_playback_committed(eventpoint)    was it committed to the stream
    #   discard_uncommitted_fragment(eventpoint)   drop a fragment that never played
    #   notify_fragment_synthesis_failed(eventpoint, reason)
    #   observe_tts_onset_preroll_ms(ms), observe_tts_retry(...)
    #   accepts_media(eventpoint)                  whether this turn's media is still wanted
