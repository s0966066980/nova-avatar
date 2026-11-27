# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The STT layer's configuration entry point for the core's config loader."""
from __future__ import annotations

from typing import Any

from src.utils.logging import logger

# STT engines removed from the product; saved settings naming one load as
# faster-whisper with the model size that config/config.yaml ships.
REMOVED_ASR_ENGINES = frozenset({"funasr"})
REMOVED_ASR_FALLBACK_MODEL = "small"


def migrate_config(section: dict[str, Any]) -> dict[str, Any]:
    """Return a saved ``asr`` section brought under the current engines."""
    migrated = dict(section)
    # The Fun-ASR-Nano engine and its output_script field were removed on
    # 2026-11-26; saved settings may still name them.
    migrated.pop("output_script", None)
    if str(migrated.get("type", "")).strip().lower() in REMOVED_ASR_ENGINES:
        logger.warning(
            f"STT 引擎「{migrated['type']}」已移除，改用 faster-whisper "
            f"{REMOVED_ASR_FALLBACK_MODEL}；請到控制台的語音辨識重新套用"
        )
        migrated["type"] = "whisper"
        migrated["model_size"] = REMOVED_ASR_FALLBACK_MODEL
    return migrated
