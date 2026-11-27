# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""An LLM engine that answers with fixed text, for tests and machines without a model.

Select it with ``llm.provider: fake``. It is not offered in the console. It
speaks in simple mode (spoken text only, no board).
"""
from __future__ import annotations

from typing import Generator, Optional

from nova_llm.base import BaseLLM

FAKE_REPLY = "這是固定的測試回覆。第二句話在這裡。"


class FakeLLM(BaseLLM):
    def __init__(self, config, parent=None, reply: str = FAKE_REPLY, **_unused):
        super().__init__(config, parent)
        self.reply = reply

    def chat_stream(self, message: str, system_prompt: Optional[str] = None, **kwargs) -> Generator[str, None, None]:
        wire = f"[[MODE:SIMPLE]]\n[[SPEECH]]\n{self.reply}\n[[END]]"
        for start in range(0, len(wire), 4):
            yield wire[start:start + 4]
