# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The TTS layer's configuration entry points for the core's config loader.

The layer owns the ``tts`` and ``matcha`` sections: ``migrate_config`` cleans a
saved ``tts`` section before it is built, ``validate_config`` checks the built
``matcha`` section, and ``migrate_voice_sources`` moves saved reference audio
into the voice library once a configuration file is loaded.
"""
from __future__ import annotations

from typing import Any

from src.tts.training.asr import WHISPER_MODELS
from src.tts.voice_library import REMOVED_TTS_FIELDS, migrate_tts_config

# sherpa-onnx CPU threads for Matcha-TTS; more than the cores only adds contention.
MAX_MATCHA_THREADS = 64
MAX_TRAINING_VRAM_GB = 1024


def migrate_config(section: dict[str, Any]) -> dict[str, Any]:
    """Return a saved ``tts`` section without the fields of removed engines."""
    return {key: value for key, value in section.items() if key not in REMOVED_TTS_FIELDS}


def validate_config(matcha: Any) -> None:
    """Raise ValueError when the ``matcha`` section breaks a limit."""
    threads = matcha.num_threads
    if type(threads) is not int or not 1 <= threads <= MAX_MATCHA_THREADS:
        raise ValueError(f"matcha.num_threads 必須是 1–{MAX_MATCHA_THREADS} 的整數：{threads!r}")
    vram = matcha.training_min_free_vram_gb
    if type(vram) not in (int, float) or not 0 < vram <= MAX_TRAINING_VRAM_GB:
        raise ValueError(f"matcha.training_min_free_vram_gb 必須是 0–{MAX_TRAINING_VRAM_GB} GB 的數字：{vram!r}")
    if matcha.training_whisper_model not in WHISPER_MODELS:
        raise ValueError(
            f"matcha.training_whisper_model 必須是 {', '.join(WHISPER_MODELS)} 之一："
            f"{matcha.training_whisper_model!r}"
        )


def migrate_voice_sources(tts: Any, *, where: str) -> bool:
    """Apply the settings-request rules to a loaded ``tts`` section (see migrate_tts_config)."""
    return migrate_tts_config(tts, where=where)
