# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""
TTS 基類模組

所有 TTS 引擎都應該繼承 BaseTTS 並實現其抽象方法。
"""

from __future__ import annotations

import queue
import re
from enum import Enum
from queue import Queue
from threading import Event, Thread
from typing import TYPE_CHECKING

from src.utils.logging import logger

if TYPE_CHECKING:
    from src.avatars.base import BaseAvatar


_EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0000FE0F"
    "\U0000200D"
    "]+"
)


def sanitize_speech_text(text: str) -> str:
    """Remove visual Markdown/emoji that speech engines may pronounce aloud."""
    value = str(text or "")
    value = re.sub(r"!\[([^]]*)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"(?m)^\s{0,3}(?:#{1,6}|>|[-+*])\s+", "", value)
    value = re.sub(r"```(?:\w+)?|`", "", value)
    value = re.sub(r"[*_~]+", "", value)
    value = _EMOJI_RE.sub("", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r" *\n+ *", "，", value)
    return value.strip(" ，")


class State(Enum):
    RUNNING = 0
    PAUSE = 1


class BaseTTS:
    """
    所有 TTS 引擎的基類，負責：
    - 統一的訊息佇列
    - 統一的渲染執行緒（process_tts）
    - 統一的取樣率 / chunk 配置
    具體引擎只需要實現 txt_to_audio。
    """

    def __init__(self, config, parent: "BaseAvatar"):
        self.config = config
        self.parent = parent

        # 20ms 一幀
        self.fps = config.audio.fps
        self.sample_rate = 16000
        # 320 samples per chunk (20ms * 16000 / 1000)
        self.chunk = self.sample_rate // self.fps

        # 文本訊息佇列
        self.msgqueue: "Queue[tuple[str, dict]]" = Queue()
        self.state: State = State.RUNNING
        self._synthesis_active = Event()

    def flush_talk(self) -> None:
        """清空佇列並暫停當前說話狀態。"""
        self.msgqueue.queue.clear()
        self.state = State.PAUSE

    def put_msg_txt(self, msg: str, datainfo: dict | None = None) -> None:
        """外部入口：放入一條待合成的文本訊息。"""
        if datainfo is None:
            datainfo = {}
        speech_text = sanitize_speech_text(msg)
        if speech_text:
            self.msgqueue.put((speech_text, datainfo))

    def has_pending_work(self) -> bool:
        """Return whether text is queued or an engine is currently synthesizing it."""
        return self._synthesis_active.is_set() or not self.msgqueue.empty()

    def notify_fragment_synthesis_failed(
        self,
        eventpoint: dict,
        reason: str,
    ) -> None:
        """Report a terminal, pre-audio synthesis failure to the owning turn."""
        if not eventpoint.get("turn_id"):
            return
        notify = getattr(self.parent, "notify_fragment_synthesis_failed", None)
        if callable(notify):
            notify(dict(eventpoint), str(reason))

    def render(self, quit_event) -> None:
        """啟動獨立執行緒持續消費佇列，呼叫具體引擎的 txt_to_audio。"""
        process_thread = Thread(target=self.process_tts, args=(quit_event,))
        process_thread.start()

    def process_tts(self, quit_event) -> None:
        """迴圈從佇列中取訊息，並呼叫 txt_to_audio。"""
        while not quit_event.is_set():
            try:
                msg: tuple[str, dict] = self.msgqueue.get(block=True, timeout=1)
                self.state = State.RUNNING
            except queue.Empty:
                continue
            self._synthesis_active.set()
            try:
                self.txt_to_audio(msg)
            except Exception:
                logger.exception("TTS synthesis failed")
            finally:
                self._synthesis_active.clear()
        logger.info("ttsreal thread stop")

    def txt_to_audio(self, msg: tuple[str, dict]):
        """
        子類必須實現：
            msg: (text, textevent)
        內部負責把音訊分幀後，通過 parent.put_audio_frame(...) 推給上層。
        """
        raise NotImplementedError
