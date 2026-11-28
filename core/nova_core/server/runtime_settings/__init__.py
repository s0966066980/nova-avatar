# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""執行時設定：把各功能的快照與套用函式組成一份（各功能的程式在同資料夾的模組）。

- `shared`：SettingsError 與共用工具。
- `llm`、`stage`、`avatar`、`speech`：各自的快照、驗證與套用。
- 這裡只有 `current_snapshot`（把各功能的快照合成），並重新匯出所有名稱，所以
  `from nova_core.server.runtime_settings import …` 維持可用。
"""
from __future__ import annotations

from typing import Any, Dict
from nova_llm.config_section import (
    DEFAULT_RESPONSE_MAX_CHARS,
    active_endpoint_name,
    load_system_prompt,
    rules_from_config,
)
from nova_contracts.avatar import AvatarService
from nova_contracts.tts import TtsService
from nova_core.server.runtime_settings.shared import SettingsError  # noqa: F401
from nova_core.server.runtime_settings.stage import (  # noqa: F401
    DEFAULT_STAGE_CAPTION_MAX_CHARS,
    MIN_STAGE_CAPTION_MAX_CHARS,
    MAX_STAGE_CAPTION_MAX_CHARS,
    DEFAULT_STAGE_IDLE_RESET_SECONDS,
    MIN_STAGE_IDLE_RESET_SECONDS,
    MAX_STAGE_IDLE_RESET_SECONDS,
    DEFAULT_CAPTION_X,
    DEFAULT_CAPTION_Y,
    DEFAULT_CAPTION_WIDTH,
    MIN_CAPTION_WIDTH,
    BOARD_STYLES,
    BOARD_PRESETS,
    DEFAULT_BOARD_STYLE,
    DEFAULT_BOARD_WIDTH,
    DEFAULT_BOARD_HEIGHT,
    DEFAULT_BOARD_TRANSPARENCY,
    DEFAULT_BOARD_X,
    DEFAULT_BOARD_Y,
    DEFAULT_BOARD_PRESET,
    DEFAULT_BOARD_OPEN_X,
    DEFAULT_BOARD_OPEN_Y,
    DEFAULT_MIC_X,
    DEFAULT_MIC_Y,
    DEFAULT_MIC_PRESET,
    MIN_BOARD_WIDTH,
    MAX_BOARD_WIDTH,
    MIN_BOARD_HEIGHT,
    MAX_BOARD_HEIGHT,
    validate_stage_caption_max_chars,
    _validate_int_range,
    validate_board_style,
    validate_board_preset,
    stage_snapshot,
    apply_stage_settings,
    apply_stage_background,
)
from nova_core.server.runtime_settings.llm import (  # noqa: F401
    _RULES_LOCK,
    MIN_BOARD_MAX_ITEMS,
    MAX_BOARD_MAX_ITEMS,
    assistant_profile_snapshot,
    validate_assistant_profile,
    ollama_native_url,
    _is_embedding_model,
    format_bytes,
    resolve_provider,
    endpoint_choices,
    reply_rules_snapshot,
    apply_reply_rules,
    apply_llm_behavior,
    validate_board_max_items,
    fetch_ollama_models,
    _fetch_ollama_tags,
    _fetch_openai_models,
    OLLAMA_ONLY_REQUEST_FIELDS,
    apply_llm_model,
    _endpoint_catalog,
    PROVIDER_LABELS,
    fetch_llm_catalog,
)
from nova_core.server.runtime_settings.avatar import (  # noqa: F401
    video_output_snapshot,
    apply_video_settings,
    apply_avatar,
    apply_mouth_quality,
    _reload_avatar,
    _release_gpu_resources,
)
from nova_core.server.runtime_settings.speech import (  # noqa: F401
    VAD_ENGINE_META,
    VAD_RANGES,
    _module_installed,
    list_vad_engines,
    vad_snapshot,
    _clamp_number,
    apply_vad_settings,
    STT_ENGINE_META,
    TTS_ENGINE_META,
    STT_MODEL_SIZES,
    STT_MODELS_BY_ENGINE,
    STT_LANGUAGES,
    STT_DEVICES,
    EDGE_TTS_ZH_TW_VOICES,
    EDGE_TTS_ZH_TW_VOICE_IDS,
    MATCHA_VOICE_MODEL_REQUIRED,
    _engine_unavailable_reason,
    _engine_available,
    _catalog,
    _stt_catalog,
    stt_snapshot,
    speech_snapshot,
    _require_no_sessions,
    apply_stt_settings,
    validate_tts_sources,
    _require_matcha_voice_model,
    _voice,
    apply_tts_settings,
    _preview_tts,
    PREVIEW_SECONDS,
    PROFILE_PREVIEW_TEXT,
    breezyvoice_server_ready,
    preview_profile_voice,
)


def current_snapshot(config, *, tts: TtsService, avatars: AvatarService) -> Dict[str, Any]:
    characters = avatars.list_characters()
    engines = avatars.list_engines(characters)
    llm = config.llm
    model_cfg = config.model
    return {
        "llm": {
            "model": llm.model,
            "endpoint": active_endpoint_name(llm),
            "endpoints": endpoint_choices(config),
            "base_url": llm.base_url,
            "provider": resolve_provider(config),
            "system_prompt": load_system_prompt(config),
            "assistant_profile": assistant_profile_snapshot(config),
            "response_max_chars": int(
                getattr(llm, "response_max_chars", DEFAULT_RESPONSE_MAX_CHARS)
            ),
            "board_max_items": validate_board_max_items(
                getattr(getattr(llm, "board", None), "max_items", 8)
            ),
            "reply_mode": (
                "streaming"
                if bool(getattr(config.reply_streaming, "enabled", False))
                else "legacy"
            ),
            "semantic_wait_seconds": float(
                getattr(config.reply_streaming, "semantic_wait_seconds", 0.5) or 0.5
            ),
            "reply_rules": rules_from_config(config),
        },
        "avatar": {
            "type": model_cfg.type,
            "avatar_id": model_cfg.avatar_id,
        },
        "avatar_quality": avatars.quality_from_model(model_cfg),
        "video": video_output_snapshot(config, avatars=avatars),
        "engines": engines,
        "characters": characters,
        "vad": vad_snapshot(config),
        "speech": speech_snapshot(config, tts=tts),
        "stage": stage_snapshot(config),
    }
