# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""
ASR 工廠類

統一根據字串型別建立不同的 ASR 引擎例項
"""

from threading import RLock
from typing import Type, Optional

from src.asr.base import BaseASR
from src.asr.engines import FunASR, WhisperASR


_ENGINE_MAP: dict[str, Type[BaseASR]] = {
    "whisper": WhisperASR,
    "funasr": FunASR,
}


def create_asr_engine(
    asr_type: str,
    config=None,
    model_size: str = "base",
    **kwargs
) -> BaseASR:
    engine_cls = _ENGINE_MAP.get(asr_type)
    if engine_cls is None:
        raise ValueError(
            f"未知的 ASR 型別: {asr_type!r}\n"
            f"支援的型別: {list(_ENGINE_MAP.keys())}"
        )
    
    # 根據不同引擎傳遞引數
    if asr_type == "whisper":
        return engine_cls(config=config, model_size=model_size)
    elif asr_type == "funasr":
        return engine_cls(config=config, model_name=model_size, **kwargs)
    else:
        return engine_cls(config=config, **kwargs)

_asr_instance: Optional[BaseASR] = None
_asr_instance_key = None
_asr_lock = RLock()


def get_asr_engine(
    asr_type: str = "whisper",
    model_size: str = "base",
    config=None,
    force_new: bool = False,
    **kwargs
) -> BaseASR:
    global _asr_instance, _asr_instance_key
    device = getattr(getattr(config, "asr", None), "device", "auto")
    language = getattr(getattr(config, "asr", None), "language", "zh")
    key = (asr_type, model_size, device, language)
    
    # Multiple /offer preparations run in executor threads.  Serialize the
    # check-and-create transition so they cannot each load a GPU model.
    with _asr_lock:
        if _asr_instance is None or force_new or _asr_instance_key != key:
            _asr_instance = create_asr_engine(
                asr_type=asr_type,
                config=config,
                model_size=model_size,
                **kwargs
            )
            _asr_instance.set_language(language)
            _asr_instance_key = key
        return _asr_instance


def release_asr_engine():
    global _asr_instance, _asr_instance_key
    with _asr_lock:
        if _asr_instance is not None:
            from src.utils.logging import logger
            logger.info('[ASR] release ASR engine resources')
            worker = getattr(_asr_instance, "worker", None)
            if worker is not None:
                worker.close()
            _asr_instance = None
            _asr_instance_key = None


def activate_asr_engine(
    engine: BaseASR,
    *,
    asr_type: str,
    model_size: str,
    config=None,
) -> BaseASR:
    """Install an already-prewarmed candidate without loading the model twice."""
    global _asr_instance, _asr_instance_key
    device = getattr(getattr(config, "asr", None), "device", "auto")
    language = getattr(getattr(config, "asr", None), "language", "zh")
    with _asr_lock:
        previous = _asr_instance
        if previous is not None and previous is not engine:
            worker = getattr(previous, "worker", None)
            if worker is not None:
                worker.close()
        _asr_instance = engine
        _asr_instance_key = (asr_type, model_size, device, language)
        return engine
