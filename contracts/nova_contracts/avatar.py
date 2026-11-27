# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Avatar rendering: PCM in, video frames and audio frames out. Stays in the core process."""
from __future__ import annotations

from threading import Event
from typing import Any, Callable, Protocol


class SpeechSource(Protocol):
    """What the renderer needs from whatever speaks for it (today a TTS engine)."""

    config: Any

    def put_msg_txt(self, msg: str, datainfo: dict | None = None) -> None: ...

    def flush_talk(self) -> None: ...

    def render(self, quit_event: Event) -> None: ...

    def has_pending_work(self) -> bool: ...


# Gets the session config and the audio sink the speech source pushes PCM into.
SpeechFactory = Callable[[Any, Any], SpeechSource]


class AvatarRenderer(Protocol):
    config: Any
    sessionid: int

    def put_msg_txt(self, msg: str, datainfo: dict | None = None) -> None: ...

    def put_audio_frame(self, samples: Any, eventpoint: dict | None = None) -> Any: ...

    def flush_talk(self) -> None: ...

    def is_speaking(self) -> bool: ...
