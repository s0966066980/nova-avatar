# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""A renderer that outputs one fixed picture, for contract tests without a GPU or weights.

It implements the ``AvatarRenderer`` contract only. It is not wired into the
WebRTC session and is not offered in the console.
"""
from __future__ import annotations

from threading import Event
from typing import Any

import numpy as np

from src.avatars.speech import SpeechFactory


class FakeAvatar:
    def __init__(self, config: Any, speech_factory: SpeechFactory, *, size: tuple[int, int] = (64, 64)) -> None:
        self.config = config
        self.sessionid = int(getattr(config, "sessionid", 0) or 0)
        self.tts = speech_factory(config, self)
        self.audio_frames: list[tuple[Any, dict]] = []
        self.speaking = False
        self._picture = np.full((size[1], size[0], 3), 127, dtype=np.uint8)

    def put_msg_txt(self, msg: str, datainfo: dict | None = None) -> None:
        self.tts.put_msg_txt(msg, dict(datainfo or {}))

    def put_audio_frame(self, samples: Any, eventpoint: dict | None = None) -> bool:
        self.speaking = True
        self.audio_frames.append((samples, dict(eventpoint or {})))
        return True

    def flush_talk(self) -> None:
        self.tts.flush_talk()
        self.speaking = False

    def is_speaking(self) -> bool:
        return self.speaking

    def render(self, quit_event: Event) -> None:
        self.tts.render(quit_event)

    def video_frame(self) -> np.ndarray:
        """The one picture this renderer always shows."""
        return self._picture.copy()
