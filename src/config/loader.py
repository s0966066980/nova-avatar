# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""配置載入器"""
import os
import re
import yaml
from dataclasses import fields
from pathlib import Path
from typing import Optional, Dict, Any
from .schema import (
    Config, AppConfig, ModelConfig, TTSConfig, ASRConfig, VADConfig, LLMConfig,
    AudioConfig, VideoConfig, CustomVideoConfig, ERNeRfConfig, TalkingGaussianConfig,
    MuseTalkQualityConfig, Wav2LipQualityConfig, ReplyStreamingConfig, StageConfig,
    ResponseRouterConfig, BoardConfig, ReplyRulesConfig, AssistantProfileConfig,
)


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
    
    # 處理 model 配置
    model_dict = config_dict.get('model', {})
    
    # 如果頂層有 ernerf 配置，合併到 model.ernerf
    if 'ernerf' in config_dict:
        if 'ernerf' not in model_dict:
            model_dict['ernerf'] = {}
        # 頂層 ernerf 優先順序更高
        model_dict['ernerf'] = _merge_dicts(model_dict.get('ernerf', {}), config_dict['ernerf'])
    
    # 如果頂層有 talkinggaussian 配置，合併到 model.talkinggaussian
    if 'talkinggaussian' in config_dict:
        if 'talkinggaussian' not in model_dict:
            model_dict['talkinggaussian'] = {}
        # 頂層 talkinggaussian 優先順序更高
        model_dict['talkinggaussian'] = _merge_dicts(model_dict.get('talkinggaussian', {}), config_dict['talkinggaussian'])
    
    # 建立 ERNeRfConfig
    ernerf_config = ERNeRfConfig(**model_dict.get('ernerf', {}))
    
    # 建立 TalkingGaussianConfig
    talkinggaussian_config = TalkingGaussianConfig(**model_dict.get('talkinggaussian', {}))
    musetalk_config = MuseTalkQualityConfig(**model_dict.get('musetalk', {}))
    wav2lip_config = Wav2LipQualityConfig(**model_dict.get('wav2lip', {}))

    # 建立 ModelConfig
    model_dict_for_init = {
        k: v
        for k, v in model_dict.items()
        if k not in ['ernerf', 'talkinggaussian', 'musetalk', 'wav2lip']
    }
    model_config = ModelConfig(
        **model_dict_for_init,
        ernerf=ernerf_config,
        talkinggaussian=talkinggaussian_config,
        musetalk=musetalk_config,
        wav2lip=wav2lip_config,
    )
    
    tts_config = TTSConfig(**config_dict.get('tts', {}))
    asr_config = ASRConfig(**config_dict.get('asr', {}))
    vad_config = VADConfig(**config_dict.get('vad', {}))
    llm_dict = dict(config_dict.get('llm', {}) or {})
    router_val = llm_dict.get('response_router')
    if isinstance(router_val, dict):
        allowed_router = {item.name for item in fields(ResponseRouterConfig)}
        llm_dict['response_router'] = ResponseRouterConfig(
            **{k: v for k, v in router_val.items() if k in allowed_router}
        )
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
    elif str(llm_dict.get('system_prompt', '') or '').strip():
        # One-way Phase-1 migration for existing runtime_overrides.yaml files.
        # The next console save persists this value under assistant_profile.
        llm_dict['assistant_profile'] = AssistantProfileConfig(
            system_prompt=str(llm_dict['system_prompt']).strip()
        )
    llm_config = LLMConfig(**llm_dict)
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

    return Config(
        app=app_config,
        model=model_config,
        tts=tts_config,
        asr=asr_config,
        vad=vad_config,
        llm=llm_config,
        audio=audio_config,
        video=video_config,
        custom_video=custom_video_config,
        reply_streaming=reply_streaming_config,
        stage=stage_config,
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
    from src.config.overrides import load_runtime_overrides

    overrides = load_runtime_overrides()
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

    # 5. 轉換為 Config 物件
    config = dict_to_config(config_dict)
    
    # 處理 -O 快捷選項
    if config.model.ernerf.O:
        config.model.ernerf.fp16 = True
        config.model.ernerf.cuda_ray = True
        config.model.ernerf.exp_eye = True
    
    return config
