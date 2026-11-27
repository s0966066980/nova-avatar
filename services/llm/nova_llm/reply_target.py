# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""What the LLM layer needs from whoever receives its reply text.

The core passes the session's avatar (or any object shaped like this); the LLM
layer never imports the renderer. Optional hooks (``notify_llm_chunk``,
``mark_stage_end``) are looked up with ``getattr`` and skipped when absent.
"""
from __future__ import annotations

from typing import Any, Protocol


class ReplyTarget(Protocol):
    config: Any
    sessionid: int

    def put_msg_txt(self, msg: str, datainfo: dict | None = None) -> None:
        """Receive one finished fragment of spoken text."""
