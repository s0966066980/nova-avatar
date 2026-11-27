# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Voice-session fakes shared by the conversation tests: no real ASR, segmenter or avatar."""

from __future__ import annotations

from io import BytesIO

from PIL import Image

from nova_contracts.stt import SttEngineSettings
from nova_contracts.tts import strip_visual_markup
from src.asr.adapter import InProcessSttService


class FakeAvatar:
    """The session avatar for core tests: its own idle renderer, recording what the core sends.

    ``put_msg_txt`` mirrors ``SpeakingAvatar``: unspeakable text never becomes a
    fragment, and only a fragment of a turn is registered with the session
    (``on_fragment_queued``). The media-fence callbacks the session attaches stay
    readable (``media_guard``, ``on_fragment_queued``, ...) so a test can play the
    part of the TTS, which reports playback to them.
    """

    direct_audio_enabled = False
    asset_epoch = 0

    def __init__(self, config=None, sessionid=0):
        self.config, self.sessionid = config, sessionid
        self.renderer = self
        self.messages = []
        self.flush_count = 0
        self.media_guard = None
        self.on_stale_drop = None
        self.on_fragment_queued = None
        self.on_fragment_failed = None

    def is_speaking(self):
        return False

    def put_msg_txt(self, text, data=None):
        text = strip_visual_markup(text)
        if not text:
            return
        eventpoint = dict(data or {})
        self.messages.append((text, eventpoint))
        if self.on_fragment_queued is not None and eventpoint.get("turn_id"):
            self.on_fragment_queued(text, eventpoint)

    def flush_talk(self):
        self.flush_count += 1

    def configure_media_fence(
        self,
        *,
        media_guard=None,
        on_stale_drop=None,
        on_fragment_queued=None,
        on_fragment_failed=None,
        **_unused,
    ):
        self.media_guard = media_guard
        self.on_stale_drop = on_stale_drop
        self.on_fragment_queued = on_fragment_queued
        self.on_fragment_failed = on_fragment_failed


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


def fake_stt(text: str = "你好"):
    """The real in-process STT service on the layer's ``fake`` engine: always hears ``text``."""
    return InProcessSttService(SttEngineSettings(engine="fake", model_size=text, device="cpu"))


def picture():
    output = BytesIO()
    Image.new('RGB', (32, 32), 'white').save(output, format='PNG')
    return output.getvalue()
