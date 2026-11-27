# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""A TTS engine that emits silence of a set length, for tests and machines without a GPU.

Select it with ``tts.type: fake``. It is not offered in the console.
"""
from __future__ import annotations

import numpy as np

from nova_tts.base import BaseTTS, State

FAKE_SECONDS_PER_FRAGMENT = 0.5


class FakeTTS(BaseTTS):
    def __init__(self, config, parent):
        super().__init__(config, parent)
        self.seconds = FAKE_SECONDS_PER_FRAGMENT

    def txt_to_audio(self, msg: tuple[str, dict]) -> None:
        _text, eventpoint = msg
        frames = max(1, round(self.seconds * self.fps))
        silence = np.zeros(self.chunk, dtype=np.float32)
        for index in range(frames):
            if self.state != State.RUNNING:
                return
            first, last = index == 0, index == frames - 1
            self.parent.put_audio_frame(
                silence.copy(), {**eventpoint, "status": "end" if last else "start" if first else "middle"},
            )
