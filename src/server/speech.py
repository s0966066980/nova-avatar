# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The core builds a session's TTS engine and hands it to the renderer."""
from __future__ import annotations

from typing import Any

from src.tts.factory import create_tts_engine


def tts_speech_factory(config: Any, audio_sink: Any):
    """Create the TTS engine configured for ``config``, pushing PCM to ``audio_sink``."""
    return create_tts_engine(config.tts.type, config, audio_sink)
