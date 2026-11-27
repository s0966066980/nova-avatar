# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""
ASR 工廠類

統一根據引擎名稱建立不同的 ASR 引擎例項。Sharing one loaded recognizer is the
in-process adapter's job (services/stt/nova_stt/adapter.py), not this module's.
"""

from typing import Type

from nova_contracts.stt import SttEngineSettings
from nova_stt.base import BaseASR
from nova_stt.engines import FakeASR, WhisperASR


# "fake" is selectable by configuration only; the console lists engines from
# runtime_settings.STT_ENGINE_META, which does not include it.
_ENGINE_MAP: dict[str, Type[BaseASR]] = {
    "whisper": WhisperASR,
    "fake": FakeASR,
}


def create_asr_engine(settings: SttEngineSettings) -> BaseASR:
    """Build (but do not load) the recognizer the settings name."""
    engine_cls = _ENGINE_MAP.get(settings.engine)
    if engine_cls is None:
        raise ValueError(
            f"未知的 ASR 型別: {settings.engine!r}\n"
            f"支援的型別: {list(_ENGINE_MAP.keys())}"
        )
    return engine_cls(model_size=settings.model_size, device=settings.device)
