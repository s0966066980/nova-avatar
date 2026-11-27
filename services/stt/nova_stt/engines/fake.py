# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""A recognizer that answers every utterance with one fixed text.

For tests and offline demos: it needs no GPU, no model weights and decodes no
audio. It is selected like any engine (``asr.type: fake``) but is not in the
console's engine list, so only configuration can choose it.
"""
from __future__ import annotations

from typing import Any, Dict

from nova_stt.base import BaseASR


class FakeASR(BaseASR):
    """``model_size`` carries the text to return; ``device`` is ignored."""

    supports_language_options = True

    def __init__(self, model_size: str = "", device: str = "auto"):
        super().__init__()
        self.text = model_size

    def _load_model(self) -> None:
        pass

    def _transcribe_bytes(self, audio_bytes: bytes, **options) -> Dict[str, Any]:
        return self._transcribe(audio_bytes, **options)

    def _transcribe(self, audio: Any, *, language: str | None = None) -> Dict[str, Any]:
        requested = self.language if language is None else language
        # "auto" detects; the fake always hears Chinese.
        detected = "zh" if requested == "auto" else requested
        segments = [{"start": 0.0, "end": 0.0, "text": self.text}] if self.text else []
        return {
            "text": self.text,
            "language": detected,
            "language_probability": 1.0,
            "confidence": 1.0,
            "segments": segments,
        }
