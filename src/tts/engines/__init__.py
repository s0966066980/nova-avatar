# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""TTS 引擎實現集中入口。

對外只需要從這裡 import 對應的引擎類即可，例如：

    from src.tts.engines import EdgeTTS, BreezyVoiceTTS
"""

from src.tts.base import BaseTTS, State
from .edge import EdgeTTS
from .breezyvoice import BreezyVoiceTTS

__all__ = [
    "BaseTTS",
    "State",
    "EdgeTTS",
    "BreezyVoiceTTS",
]
