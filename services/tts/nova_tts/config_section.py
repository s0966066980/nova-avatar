# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
# The configuration dataclasses below were moved here from core/nova_core/config/schema.py,
# which is derived from Kedreamix/Linly-Talker-Stream (Apache-2.0) and modified by
# HongXian0903, 2026. See LICENSE and NOTICE.

"""The TTS layer's rules for its configuration sections, for the core.

The layer owns the ``tts`` and ``matcha`` sections and the ``tts`` part of
every role profile. ``migrate_config`` cleans a saved ``tts`` section before it
is built, ``validate_config`` checks the built ``matcha`` section, and
``migrate_voice_sources`` / ``migrate_profile_voice`` move saved reference audio
into the voice library once a configuration file or role library is loaded.
``voice`` and ``engine_settings`` turn the sections into the contract's DTOs.

The checks here name voice-library, ``models/`` and voice-model IDs, so some of
them read the layer's catalogs on disk. Refusals are ``ValueError`` whose text
is shown to the administrator.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from nova_contracts.tts import TtsEngineSettings, TtsVoice
from nova_tts import cosyvoice_runtime, voice_library
from nova_tts.training.asr import WHISPER_MODELS
from nova_tts.voice_library import REMOVED_TTS_FIELDS, migrate_tts_config


@dataclass
class TTSConfig:
    voice_en_us: str = "en-US-JennyNeural"
    """TTS 配置"""
    type: str = "edgetts"  # edgetts | breezyvoice | matcha
    # Edge 聲線名稱、BreezyVoice 的音訊庫 ID，或 Matcha 的聲線模型 ID（models/tts/<id>）
    ref_file: str = "zh-TW-HsiaoChenNeural"
    ref_text: Optional[str] = None  # 已停用：逐字稿只來自音訊庫，載入與儲存時清除
    tts_server: str = ""  # BreezyVoice 服務（只接受本機）；空白為 127.0.0.1:50000
    model: str = ""  # BreezyVoice：models/ 清單 ID；空白為 models/BreezyVoice
    edge_persistent_worker: bool = True
    edge_prefetch: bool = True
    edge_connection_reuse: bool = True


@dataclass
class MatchaConfig:
    """Matcha-TTS 的伺服器設定，所有數位人設定檔共用（不屬於任何設定檔）"""
    num_threads: int = 4  # sherpa-onnx 在 CPU 上合成的執行緒數
    training_min_free_vram_gb: float = 8.0  # 聲線訓練：剩餘顯存低於此值（GB）時拒絕開始
    training_whisper_model: str = "small"  # 訓練前逐字稿比對用的 faster-whisper 大小（在 CPU 執行）


# sherpa-onnx CPU threads for Matcha-TTS; more than the cores only adds contention.
MAX_MATCHA_THREADS = 64
MAX_TRAINING_VRAM_GB = 1024

# Every engine a configuration may name; the console lists only voice_library.TTS_ENGINES.
ENGINES = voice_library.CONFIGURABLE_TTS_ENGINES
# Engines whose ``ref_file`` is a voice-library recording with its transcript.
REFERENCE_AUDIO_ENGINES = voice_library.REFERENCE_AUDIO_ENGINES
# Engines whose ``ref_file`` is a voice-model ID.
VOICE_MODEL_ENGINES = voice_library.VOICE_MODEL_ENGINES
# Engines that speak en-US as well as zh-TW.
ENGLISH_ENGINES = voice_library.ENGLISH_TTS_ENGINES
# The Edge voices a conversation may switch to for en-US.
EDGE_ENGLISH_VOICES = voice_library.EDGE_TTS_EN_US_VOICES


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


def migrate_profile_voice(values: dict, *, where: str) -> bool:
    """``migrate_voice_sources`` for a role profile's saved ``tts`` mapping; mutates it."""
    return voice_library.migrate_tts_values(values, where=where)


def drop_stale_transcript(values: dict, where: str) -> bool:
    """Clear a saved ``ref_text``: the transcript comes only from the voice library."""
    return voice_library.drop_stale_transcript(values, where)


def check_voice_values(engine: str, ref_file: Any, tts_server: Any, model: Any) -> dict[str, str]:
    """``ref_file`` / ``tts_server`` / ``model`` of a ``tts`` section, normalized.

    ``ref_file`` must be a voice-library ID, a voice-model ID (format only) or
    an Edge voice name, ``model`` a ``models/`` catalog ID (a BreezyVoice model
    folder for BreezyVoice) and ``tts_server`` a loopback address.
    """
    values = {
        "ref_file": voice_library.check_reference(engine, ref_file),
        "tts_server": voice_library.check_tts_server(tts_server),
        "model": voice_library.check_model(model),
    }
    if engine == "breezyvoice" and values["model"]:
        try:
            cosyvoice_runtime.resolve_model_dir(values["model"])
        except FileNotFoundError as exc:
            raise ValueError(str(exc)) from None
    return values


def voice_transcript(voice_id: Any) -> str:
    """What a library recording says; "" when none is chosen or recorded."""
    return voice_library.voice_transcript(voice_id)


def check_voice_model_installed(voice_id: str) -> None:
    """Refuse a voice-model ID that is not installed under ``models/tts`` now."""
    voice_library.check_voice_model_installed(voice_id)


def server_identity(tts_server: str = "", model: str = "") -> tuple[str, int, str]:
    """The BreezyVoice server a voice needs: host, port and model ID, defaults filled in."""
    return cosyvoice_runtime.server_identity(tts_server, model)


def removed_engine_notice() -> str:
    """Why saved settings that named a removed engine now use Edge TTS (console text)."""
    return voice_library.removed_engine_notice()


def clear_removed_engine_notice() -> None:
    """The administrator has chosen voices again."""
    voice_library.clear_removed_engine_notice()


def voice(tts: Any) -> TtsVoice:
    """The voice a ``tts`` section (``TTSConfig``) speaks with."""
    return TtsVoice(
        engine=str(tts.type).strip().lower(),  # type: ignore[arg-type]  # validated by TtsVoice
        voice=str(tts.ref_file or "").strip(),
        server=str(tts.tts_server or "").strip(),
        model=str(tts.model or "").strip(),
        edge_persistent_worker=bool(tts.edge_persistent_worker),
        edge_prefetch=bool(tts.edge_prefetch),
        edge_connection_reuse=bool(tts.edge_connection_reuse),
    )


def engine_settings(config: Any) -> TtsEngineSettings:
    """What every voice of the process shares, from ``audio`` and ``matcha``."""
    matcha = config.matcha
    return TtsEngineSettings(
        frames_per_second=int(config.audio.fps),
        matcha_threads=int(matcha.num_threads),
        training_min_free_vram_gb=float(matcha.training_min_free_vram_gb),
        training_whisper_model=str(matcha.training_whisper_model),
    )
