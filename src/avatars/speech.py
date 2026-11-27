# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""What the avatar renderer needs from whatever speaks for it.

The core builds the speech source (today a TTS engine) and hands the renderer a
factory for it; the renderer never imports the TTS layer. ``SpeechFactory`` gets
the session config and the audio sink the speech source must push PCM frames
into, and returns an object with the members below.
"""
from __future__ import annotations

from threading import Event
from typing import Any, Callable, Protocol


class SpeechSource(Protocol):
    config: Any

    def put_msg_txt(self, msg: str, datainfo: dict | None = None) -> None:
        """Queue one fragment of text to be spoken."""

    def flush_talk(self) -> None:
        """Drop queued text and stop the current utterance."""

    def render(self, quit_event: Event) -> None:
        """Start the worker that turns queued text into audio."""

    def has_pending_work(self) -> bool:
        """Whether text is queued or being synthesized."""


SpeechFactory = Callable[[Any, Any], SpeechSource]
