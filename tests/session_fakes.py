# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Voice-session fakes shared by the conversation tests: no real ASR, segmenter or avatar."""

from __future__ import annotations

from io import BytesIO

from PIL import Image

from nova_contracts.stt import Transcription


class FakeAvatar:
    def __init__(self):
        self.messages = []
        self.flush_count = 0
        self.media_guard = None
        self.on_stale_drop = None
        self.on_fragment_queued = None

    def put_msg_txt(self, text, data=None):
        eventpoint = data or {}
        self.messages.append((text, eventpoint))
        if self.on_fragment_queued is not None:
            self.on_fragment_queued(text, eventpoint)

    def flush_talk(self):
        self.flush_count += 1

    def configure_media_fence(
        self,
        *,
        media_guard,
        on_stale_drop,
        on_fragment_queued=None,
        **_unused,
    ):
        self.media_guard = media_guard
        self.on_stale_drop = on_stale_drop
        self.on_fragment_queued = on_fragment_queued


class FakeSegmenter:
    def __init__(self, segment=None):
        self.segment = segment
        self.is_speaking = False
        self.reset_count = 0

    def process(self, _pcm):
        if self.segment is None:
            return []
        segment, self.segment = self.segment, None
        return [segment]

    def flush(self):
        return []

    def reset(self):
        self.reset_count += 1
        self.is_speaking = False


class FakeStt:
    """An SttService that always hears 你好."""

    def transcribe(self, _audio, _options):
        return Transcription(text="你好", language="zh")


def picture():
    output = BytesIO()
    Image.new('RGB', (32, 32), 'white').save(output, format='PNG')
    return output.getvalue()
