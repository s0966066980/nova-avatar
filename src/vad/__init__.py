# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Silero VAD speech endpointing."""

from .base import BaseVAD
from .engines import SileroVAD
from .factory import (
    create_vad_engine,
    create_vad_from_config,
    get_vad_engine,
    get_vad_engine_from_config,
    list_vad_types,
    release_vad_engine,
)
from .segmenter import (
    SpeechSegment,
    VADSegmenter,
    detect_speech_segments,
    extract_speech,
)
from .service import VADOutcome, create_segmenter, preprocess_audio_bytes

__all__ = [
    # base
    "BaseVAD",
    # engines
    "SileroVAD",
    # factory
    "create_vad_engine",
    "create_vad_from_config",
    "get_vad_engine",
    "get_vad_engine_from_config",
    "release_vad_engine",
    "list_vad_types",
    # segmenter
    "SpeechSegment",
    "VADSegmenter",
    "detect_speech_segments",
    "extract_speech",
    # service
    "VADOutcome",
    "preprocess_audio_bytes",
    "create_segmenter",
]
