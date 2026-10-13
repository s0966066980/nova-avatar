# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""PCM output plus a tiny transport clock, with no avatar inference."""
import numpy as np
from av import VideoFrame
from .base import BaseAvatar, enqueue_media_frame


def clock_image(milliseconds):
    # 0xA5 is a signature; the remaining 24 bits are session media milliseconds.
    value = 0xA5000000 | (int(milliseconds) & 0xFFFFFF)
    pixels = np.zeros((32, 64, 3), dtype=np.uint8)
    for bit in range(32):
        if value & (1 << (31 - bit)):
            row, column = divmod(bit, 8)
            pixels[row * 8:(row + 1) * 8, column * 8:(column + 1) * 8] = 255
    return pixels


class _NoMouthStream:
    def offer_audio_frame(self, *args):
        return True

    def flush_talk(self):
        pass


class PrerecordedAvatar(BaseAvatar):
    clock_only = True

    def __init__(self, config):
        super().__init__(config)
        self.audio_stream = _NoMouthStream()

    def render(self, quit_event, loop, audio_track, video_track):
        self.configure_audio_output(audio_track, loop)
        self.tts.render(quit_event)
        try:
            while not quit_event.is_set():
                frame = VideoFrame.from_ndarray(clock_image(0), format="bgr24")
                if not enqueue_media_frame(video_track, frame, None, loop, quit_event):
                    break
                quit_event.wait(0.035)
        finally:
            self.stop_audio_output()

    def put_audio_frame(self, audio_chunk, datainfo=None):
        # Never enqueue speech before its direct transport has been attached.
        if not self.direct_audio_enabled:
            return False
        return super().put_audio_frame(audio_chunk, datainfo or {})
