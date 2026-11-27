# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""What the core's configuration loader may ask of the TTS layer.

The loader validates and migrates saved settings through these names only, so a
change inside the TTS layer cannot silently break loading.
"""
from src.tts.training.asr import WHISPER_MODELS
from src.tts.voice_library import REMOVED_TTS_FIELDS, migrate_tts_config

__all__ = ["REMOVED_TTS_FIELDS", "WHISPER_MODELS", "migrate_tts_config"]
