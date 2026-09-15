# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""TTS 引擎實現集中入口。

對外只需要從這裡 import 對應的引擎類即可，例如：

    from src.tts.engines import EdgeTTS, SovitsTTS
"""

from src.tts.base import BaseTTS, State
from .edge import EdgeTTS
from .fish import FishTTS
from .sovits import SovitsTTS
from .cosyvoice import CosyVoiceTTS
from .indextts2 import IndexTTS2
from .xtts import XTTS

__all__ = [
    "BaseTTS",
    "State",
    "EdgeTTS",
    "FishTTS",
    "SovitsTTS",
    "CosyVoiceTTS",
    "IndexTTS2",
    "XTTS",
]
