# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""Avatar 工廠類"""
from typing import Any
from copy import deepcopy
from .base import BaseAvatar


def create_avatar(config: Any, model: Any, avatar: Any, sessionid: int) -> BaseAvatar:
    """
    根據配置建立對應的 Avatar 例項
    
    Args:
        config: 配置物件
        model: 載入的模型
        avatar: avatar 資料(幀列表、座標等)
        sessionid: 會話 ID
    
    Returns:
        BaseAvatar: Avatar 例項
    """
    model_type = config.model.type
    # 每個 session 使用獨立 config，避免併發會話互相汙染（sessionid / customopt 等）
    session_config = deepcopy(config)
    session_config.sessionid = sessionid
    
    # 延遲匯入，避免啟動時載入全部模型依賴
    if model_type == 'wav2lip':
        from .wav2lip.avatar import Wav2LipAvatar
        return Wav2LipAvatar(session_config, model, avatar)
    elif model_type == 'musetalk':
        from .musetalk.avatar import MuseTalkAvatar
        return MuseTalkAvatar(session_config, model, avatar)
    elif model_type == 'ultralight':
        from .ultralight.avatar import UltralightAvatar
        return UltralightAvatar(session_config, model, avatar)
    elif model_type == 'ernerf':
        from .ernerf.avatar import ERNeRFAvatar
        return ERNeRFAvatar(session_config, model, avatar)
    elif model_type == 'talkinggaussian':
        from .talkinggaussian.avatar import TalkingGaussianAvatar
        return TalkingGaussianAvatar(session_config, model, avatar)
    else:
        raise ValueError(f"Unknown model type: {model_type}")


def prepare_avatar_model(config: Any):
    """
    預載入 Avatar 模型
    
    Args:
        config: 配置物件
    
    Returns:
        tuple: (model, avatar) 模型和 avatar 資料
    """
    model_type = config.model.type
    
    if model_type == 'musetalk':
        from .musetalk.avatar import load_model, load_avatar, warm_up
        model = load_model()
        avatar = load_avatar(config.model.avatar_id)
        warm_up(config.model.batch_size, model)
        return model, avatar
    elif model_type == 'wav2lip':
        from .wav2lip.avatar import load_model, load_avatar, warm_up
        from .catalog import resolve_wav2lip_weights
        ckpt = resolve_wav2lip_weights()
        if ckpt is None:
            raise FileNotFoundError(
                "缺少 Wav2Lip 權重，請放置 models/wav2lip.pth 或 models/wav2lip256.pth"
            )
        model = load_model(str(ckpt))
        avatar = load_avatar(config.model.avatar_id)
        warm_up(config.model.batch_size, model, 256)
        return model, avatar
    elif model_type == 'ultralight':
        from .ultralight.avatar import load_model, load_avatar, warm_up
        model = load_model(config)
        avatar = load_avatar(config.model.avatar_id)
        warm_up(config.model.batch_size, avatar, 160)
        return model, avatar
    elif model_type == 'ernerf':
        from .ernerf.avatar import load_model, load_avatar
        model = load_model(config)
        avatar = load_avatar(config)
        return model, avatar
    elif model_type == 'talkinggaussian':
        from .talkinggaussian.avatar import load_model, load_avatar
        model = load_model(config)
        avatar = load_avatar(config)
        return model, avatar
    else:
        raise ValueError(f"Unknown model type: {model_type}")


def load_avatar_data(config: Any):
    """只過載角色素材，不重新載入引擎權重。"""
    model_type = config.model.type
    avatar_id = config.model.avatar_id

    if model_type == "musetalk":
        from .musetalk.avatar import load_avatar
        return load_avatar(avatar_id)
    if model_type == "wav2lip":
        from .wav2lip.avatar import load_avatar
        return load_avatar(avatar_id)
    if model_type == "ultralight":
        from .ultralight.avatar import load_avatar
        return load_avatar(avatar_id)
    if model_type == "ernerf":
        from .ernerf.avatar import load_avatar
        return load_avatar(config)
    if model_type == "talkinggaussian":
        from .talkinggaussian.avatar import load_avatar
        return load_avatar(config)
    raise ValueError(f"Unknown model type: {model_type}")
