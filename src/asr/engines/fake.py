# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""A recognizer that returns fixed text, for tests and machines without a GPU or weights.

Select it with ``asr.type: fake``. It is not offered in the console.
"""
from __future__ import annotations

from typing import Any, Dict

from src.asr.base import BaseASR

FAKE_TRANSCRIPT = "你好，請問今天有什麼活動？"


class FakeASR(BaseASR):
    supports_language_options = True

    def __init__(self, config=None, model_size: str = "base"):
        super().__init__(config)
        self.model_size = model_size
        self.text = FAKE_TRANSCRIPT

    def _load_model(self) -> None:
        return None

    def _transcribe(self, audio_path: str, **options: Any) -> Dict[str, Any]:
        return {"text": self.text, "language": options.get("language") or self.language, "confidence": 1.0}
