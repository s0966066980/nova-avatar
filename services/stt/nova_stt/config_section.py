# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
# The configuration dataclasses below were moved here from core/nova_core/config/schema.py,
# which is derived from Kedreamix/Linly-Talker-Stream (Apache-2.0) and modified by
# HongXian0903, 2026. See LICENSE and NOTICE.

"""The STT layer's configuration entry point for the core's config loader."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nova_core.utils.logging import logger


@dataclass
class ASRConfig:
    """ASR 語音識別配置"""
    mode: str = "server"  # 互動麥克風固定由 WebRTC 傳到伺服器
    type: str = "whisper"  # faster-whisper, the only STT engine
    model_size: str = "base"  # engine-specific model name or Hugging Face/local path
    language: str = "zh"  # /asr 上傳辨識：zh | en | auto（只在中英文間偵測）；語音輪次一律自動偵測
    device: str = "auto"  # auto | cpu | cuda
    min_speech_ms: int = 450  # 短促咳嗽、敲擊等不送入 ASR／LLM
    min_audio_rms: float = 0.003  # int16 正規化後的最低音量
    min_confidence: float = 0.35  # 引擎提供信心分數時的最低接受值


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
