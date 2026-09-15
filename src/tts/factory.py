# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""TTS 工廠類

統一根據字串型別建立不同的 TTS 引擎例項。
"""

from typing import Type

from .engines import (
    BaseTTS,
    CosyVoiceTTS,
    EdgeTTS,
    FishTTS,
    IndexTTS2,
    SovitsTTS,
    XTTS,
)

_ENGINE_MAP: dict[str, Type[BaseTTS]] = {
    "edgetts": EdgeTTS,
    "gpt-sovits": SovitsTTS,
    "xtts": XTTS,
    "cosyvoice": CosyVoiceTTS,
    "fun-cosyvoice3": CosyVoiceTTS,
    "fishtts": FishTTS,
    "indextts2": IndexTTS2,
}


def create_tts_engine(tts_type: str, config, parent) -> BaseTTS:
    """
    根據型別建立 TTS 引擎
    """
    # 統一入口，便於擴充套件不同 TTS 提供方
    engine_cls = _ENGINE_MAP.get(tts_type)
    if engine_cls is None:
        raise ValueError(f"未知的 TTS 型別: {tts_type!r}")
    return engine_cls(config, parent)
