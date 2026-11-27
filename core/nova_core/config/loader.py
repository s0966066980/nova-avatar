# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""配置載入器"""
import os
import re
import yaml
from dataclasses import fields
from pathlib import Path
from typing import Optional, Dict
from .schema import (
    Config, AppConfig, ModelConfig, TTSConfig, MatchaConfig, ASRConfig, VADConfig, LLMConfig,
    AudioConfig, VideoConfig, CustomVideoConfig,
    MuseTalkQualityConfig, ReplyStreamingConfig, StageConfig,
    BoardConfig, ReplyRulesConfig, AssistantProfileConfig, GreetingConfig, ConversationConfig,
)
from nova_stt import config_section as asr_section
from nova_render import config_section as avatar_section
from nova_llm import config_section as llm_section
from nova_tts import config_section as tts_section
from nova_core.utils.logging import logger


def _merge_dicts(base: Dict, override: Dict) -> Dict:
    """
    深度合併兩個字典
    
    Args:
        base: 基礎字典
        override: 覆蓋字典
    
    Returns:
        合併後的字典
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def load_yaml_config(config_file: Path) -> Dict:
    """載入 YAML 配置檔案，支援環境變數插值"""
    if not config_file.exists():
        return {}
    
    with open(config_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 替換 ${VAR_NAME} 格式的環境變數，只替換存在的環境變數
    def replace_env_var(match):
        var_name = match.group(1)
        value = os.getenv(var_name)
        # 只有環境變數存在時才替換，否則保持原樣
        return value if value is not None else match.group(0)
    
    content = re.sub(r'\$\{([^}]+)\}', replace_env_var, content)
    config_dict = yaml.safe_load(content) or {}
    
    return config_dict


def dict_to_config(config_dict: Dict) -> Config:
    """
    將字典轉換為 Config 物件
    
    Args:
        config_dict: 配置字典
    
    Returns:
        Config 物件
    """
    app_config = AppConfig(**config_dict.get('app', {}))
    
    # Each processing layer migrates and validates its own sections; the core
    # only builds the dataclasses.
    model_dict = avatar_section.migrate_config(config_dict.get('model', {}) or {})
    musetalk_config = MuseTalkQualityConfig(**model_dict.pop('musetalk', {}))
    model_config = ModelConfig(**model_dict, musetalk=musetalk_config)

    tts_config = TTSConfig(**tts_section.migrate_config(config_dict.get('tts', {}) or {}))
    matcha_config = MatchaConfig(**(config_dict.get('matcha', {}) or {}))
    tts_section.validate_config(matcha_config)
    asr_config = ASRConfig(**asr_section.migrate_config(config_dict.get('asr', {}) or {}))
    vad_config = VADConfig(**config_dict.get('vad', {}))
    llm_dict = llm_section.migrate_config(config_dict.get('llm', {}) or {})
    board_val = llm_dict.get('board')
    if isinstance(board_val, dict):
        allowed_board = {item.name for item in fields(BoardConfig)}
        llm_dict['board'] = BoardConfig(
            **{k: v for k, v in board_val.items() if k in allowed_board}
        )
    rules_val = llm_dict.get('reply_rules')
    if isinstance(rules_val, dict):
        allowed_rules = {item.name for item in fields(ReplyRulesConfig)}
        llm_dict['reply_rules'] = ReplyRulesConfig(
            **{k: v for k, v in rules_val.items() if k in allowed_rules}
        )
    profile_val = llm_dict.get('assistant_profile')
    if isinstance(profile_val, dict):
        allowed_profile = {item.name for item in fields(AssistantProfileConfig)}
        llm_dict['assistant_profile'] = AssistantProfileConfig(
            **{k: v for k, v in profile_val.items() if k in allowed_profile}
        )
    llm_config = LLMConfig(**llm_dict)
    llm_section.validate_config(llm_config)
    audio_config = AudioConfig(**config_dict.get('audio', {}))
    video_config = VideoConfig(**config_dict.get('video', {}))
    custom_video_config = CustomVideoConfig(**config_dict.get('custom_video', {}))
    reply_streaming_config = ReplyStreamingConfig(**config_dict.get('reply_streaming', {}))
    stage_dict = config_dict.get('stage', {}) or {}
    if not isinstance(stage_dict, dict):
        stage_dict = {}
    allowed_stage = {item.name for item in fields(StageConfig)}
    stage_config = StageConfig(
        **{key: value for key, value in stage_dict.items() if key in allowed_stage}
    )

    from nova_core.greetings.content import validate_content, validate_interval
    greeting = GreetingConfig(**validate_content(config_dict.get("greeting")))
    if type(stage_config.idle_greeting_enabled) is not bool:
        raise ValueError("招呼開關須為布林值")
    stage_config.idle_greeting_seconds = validate_interval(stage_config.idle_greeting_seconds)

    return Config(
        app=app_config,
        model=model_config,
        tts=tts_config,
        matcha=matcha_config,
        asr=asr_config,
        vad=vad_config,
        llm=llm_config,
        audio=audio_config,
        video=video_config,
        custom_video=custom_video_config,
        reply_streaming=reply_streaming_config,
        stage=stage_config,
        greeting=greeting,
        conversation=ConversationConfig(**config_dict.get('conversation', {})),
    )


def load_config(
    config_file: Optional[str] = None,
) -> Config:
    """
    載入配置
    
    Args:
        config_file: 指定配置檔案路徑
    
    Returns:
        Config: 最終配置物件
    """
    from ..utils.paths import get_project_root, get_config_dir
    
    # 1. 載入預設配置（起始為空，後續逐步合併）
    config_dict = {}
    
    # 2. 載入指定的配置檔案（如果有傳入 --config）
    if config_file:
        config_path = Path(config_file)
        if not config_path.is_absolute():
            config_path = get_project_root() / config_path
        
        if config_path.exists():
            file_config = load_yaml_config(config_path)
            config_dict = _merge_dicts(config_dict, file_config)
    
    # 3. 如果沒有指定配置檔案，載入預設 config.yaml
    if not config_file:
        default_config_file = get_config_dir() / "config.yaml"
        if default_config_file.exists():
            default_config = load_yaml_config(default_config_file)
            config_dict = _merge_dicts(config_dict, default_config)
    
    # 4. 合併設定面板寫入的執行時覆蓋（llm.model / 數字人引擎與角色）
    from nova_core.config.overrides import load_runtime_overrides
    from nova_core.utils.logging import logger

    # An isolated diagnostic profile must not inherit the control panel's
    # selected local LLM or avatar. Saved preferences remain untouched.
    overrides_enabled = os.getenv("NOVA_AVATAR_RUNTIME_OVERRIDES_ENABLED", "1").strip().lower()
    if overrides_enabled not in {"0", "1", "false", "true"}:
        raise ValueError("NOVA_AVATAR_RUNTIME_OVERRIDES_ENABLED must be 0, 1, false, or true")
    overrides = load_runtime_overrides() if overrides_enabled in {"1", "true"} else {}
    # The main role profile is the only source of the default voice. A tts
    # block an older console saved is ignored here and dropped on the next save.
    if overrides.pop("tts", None) is not None:
        logger.info("runtime_overrides.yaml 的 tts 區塊已不再使用：預設聲音改由主數位人設定檔決定")
    if overrides:
        config_dict = _merge_dicts(config_dict, overrides)

    # Process-scoped rollout switch for an isolated soak/canary.  The checked-in
    # default remains off until the real-hardware gate passes.
    reply_streaming_env = os.getenv("NOVA_AVATAR_REPLY_STREAMING_ENABLED")
    if reply_streaming_env is None:
        legacy_env_name = "_".join(("LINLY", "REPLY", "STREAMING", "ENABLED"))
        reply_streaming_env = os.getenv(legacy_env_name)
    if reply_streaming_env is not None:
        normalized = reply_streaming_env.strip().lower()
        if normalized not in {"0", "1", "false", "true"}:
            raise ValueError(
                "NOVA_AVATAR_REPLY_STREAMING_ENABLED must be 0, 1, false, or true"
            )
        config_dict = _merge_dicts(
            config_dict,
            {"reply_streaming": {"enabled": normalized in {"1", "true"}}},
        )

    # Process-only control for cold/warm comparisons; never persist a benchmark
    # choice into the administrator's runtime settings.
    prewarm_env = os.getenv("NOVA_AVATAR_PREWARM_ENABLED")
    if prewarm_env is not None:
        normalized = prewarm_env.strip().lower()
        if normalized not in {"0", "1", "false", "true"}:
            raise ValueError("NOVA_AVATAR_PREWARM_ENABLED must be 0, 1, false, or true")
        config_dict = _merge_dicts(
            config_dict, {"app": {"prewarm": normalized in {"1", "true"}}},
        )

    # 5. 轉換為 Config 物件
    config = dict_to_config(config_dict)

    # Saved TTS sources obey the same rules as settings requests: reference
    # audio paths move into the voice library or are cleared.
    tts_section.migrate_voice_sources(config.tts, where="設定檔")
    
    return config
