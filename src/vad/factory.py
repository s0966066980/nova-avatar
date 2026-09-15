# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""
VAD 工廠類

統一建立 Silero VAD。WebRTC 是媒體傳輸協議，不是此應用的端點檢測器。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Type

from src.utils.logging import logger
from src.vad.base import BaseVAD
from src.vad.engines import SileroVAD

_ENGINE_MAP: Dict[str, Type[BaseVAD]] = {
    "silero": SileroVAD,
    "silero_vad": SileroVAD,
}


def list_vad_types() -> list:
    """可選的 VAD 型別（不含別名）"""
    return ["silero"]


def create_vad_engine(
    vad_type: str = "silero",
    config=None,
    sample_rate: int = 16000,
    frame_ms: int = 0,
    threshold: float = 0.5,
    **kwargs,
) -> BaseVAD:
    """
    建立 VAD 引擎例項

    Args:
        vad_type: silero
        config: 全域性配置物件（可選）
        sample_rate: 取樣率
        frame_ms: 期望幀長（毫秒），引擎會歸一化到自己支援的檔位
        threshold: 語音機率閾值（silero 有效）
        **kwargs: 引擎專屬引數
            silero: model_path / device / use_onnx
    """
    engine_cls = _ENGINE_MAP.get((vad_type or "").strip().lower())
    if engine_cls is None:
        raise ValueError(
            f"未知的 VAD 型別: {vad_type!r}\n"
            f"支援的型別: {list_vad_types()}"
        )

    return engine_cls(
        sample_rate=sample_rate,
        frame_ms=frame_ms,
        threshold=threshold,
        config=config,
        **kwargs,
    )


def create_vad_from_config(vad_config, config=None) -> BaseVAD:
    """按 VADConfig（config.yaml 的 vad 段）建立引擎"""
    return create_vad_engine(
        vad_type=getattr(vad_config, "type", "silero"),
        config=config,
        sample_rate=getattr(vad_config, "sample_rate", 16000),
        frame_ms=getattr(vad_config, "frame_ms", 0),
        threshold=getattr(vad_config, "threshold", 0.5),
        aggressiveness=getattr(vad_config, "aggressiveness", 2),
        model_path=getattr(vad_config, "model_path", ""),
        device=getattr(vad_config, "device", "cpu"),
        use_onnx=getattr(vad_config, "use_onnx", False),
    )


_vad_instance: Optional[BaseVAD] = None
_vad_signature: Optional[tuple] = None


def _signature(vad_type: str, kwargs: Dict[str, Any]) -> tuple:
    return (str(vad_type).strip().lower(), tuple(sorted((k, str(v)) for k, v in kwargs.items())))


def get_vad_engine(
    vad_type: str = "silero",
    config=None,
    force_new: bool = False,
    **kwargs,
) -> BaseVAD:
    """
    獲取 Silero VAD 單例；引數變化時自動重建。
    """
    global _vad_instance, _vad_signature

    signature = _signature(vad_type, kwargs)
    if _vad_instance is None or force_new or signature != _vad_signature:
        if _vad_instance is not None:
            logger.info(f'[VAD] 切換引擎: {_vad_signature[0] if _vad_signature else None} -> {vad_type}')
            _vad_instance.close()
        _vad_instance = create_vad_engine(vad_type=vad_type, config=config, **kwargs)
        _vad_signature = signature

    return _vad_instance


def get_vad_engine_from_config(vad_config, config=None, force_new: bool = False) -> BaseVAD:
    """按配置獲取單例引擎"""
    return get_vad_engine(
        vad_type=getattr(vad_config, "type", "silero"),
        config=config,
        force_new=force_new,
        sample_rate=getattr(vad_config, "sample_rate", 16000),
        frame_ms=getattr(vad_config, "frame_ms", 0),
        threshold=getattr(vad_config, "threshold", 0.5),
        aggressiveness=getattr(vad_config, "aggressiveness", 2),
        model_path=getattr(vad_config, "model_path", ""),
        device=getattr(vad_config, "device", "cpu"),
        use_onnx=getattr(vad_config, "use_onnx", False),
    )


def release_vad_engine():
    """釋放 VAD 引擎"""
    global _vad_instance, _vad_signature
    if _vad_instance is not None:
        logger.info('[VAD] release VAD engine resources')
        _vad_instance.close()
        _vad_instance = None
        _vad_signature = None


__all__ = [
    "create_vad_engine",
    "create_vad_from_config",
    "get_vad_engine",
    "get_vad_engine_from_config",
    "release_vad_engine",
    "list_vad_types",
]
