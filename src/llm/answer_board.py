# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""口語摘要與看板回覆分流：在 TTS 之前把朗讀文字與條列項目拆開。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

BOARD_START = "<<<BOARD"
BOARD_END = "BOARD>>>"


@dataclass(frozen=True)
class BoardItem:
    title: str
    body: str


@dataclass(frozen=True)
class BoardPayload:
    title: str
    items: tuple[BoardItem, ...] = field(default_factory=tuple)


def with_board_instruction(prompt: str) -> str:
    """口語摘要與看板區塊的輸出契約；簡單回覆不得輸出看板標記。"""
    return (
        f"{prompt.rstrip()}\n\n"
        "【看板回覆】若問題需要步驟、清單、比較或規劃，先寫 1 到 3 句口語摘要"
        "（只說結論與必須口述的前提，不要逐項朗讀），接著單獨輸出：\n"
        f"{BOARD_START}\n"
        "標題：...\n"
        "- 項目標題：一到兩句說明\n"
        f"{BOARD_END}\n"
        "簡單問候或單一事實只輸出可朗讀短答，不要輸出看板標記。"
        "看板區塊不會被朗讀，不計入口語字數。"
    )


def _hold_marker_prefix(buffer: str) -> tuple[str, str]:
    """只留下可能是看板標記開頭的後綴，其餘立刻當作口語送出。"""
    max_keep = len(BOARD_START) - 1
    for keep in range(min(max_keep, len(buffer)), 0, -1):
        if BOARD_START.startswith(buffer[-keep:]):
            return buffer[:-keep], buffer[-keep:]
    return buffer, ""


def parse_board_block(raw: str) -> Optional[BoardPayload]:
    """把看板區塊解析成標題與條列；沒有完整項目時不啟用看板。"""
    lines = [line.strip() for line in str(raw or "").replace("\r\n", "\n").split("\n")]
    lines = [line for line in lines if line and line not in {BOARD_START, BOARD_END}]
    if not lines:
        return None
    title = ""
    items: list[BoardItem] = []
    for line in lines:
        stripped = line.lstrip("•*-").strip()
        numbered = _split_numbered(line)
        if numbered is not None:
            items.append(_item_from_text(numbered))
            continue
        if line.startswith(("-", "*", "•")):
            items.append(_item_from_text(stripped))
            continue
        if not title:
            title = stripped.removeprefix("標題").lstrip("：:").strip() or stripped
            continue
        items.append(_item_from_text(stripped))
    items = [item for item in items if item.title]
    if len(items) < 2:
        return None
    return BoardPayload(title=title or items[0].title, items=tuple(items))


def _split_numbered(line: str) -> Optional[str]:
    text = line.strip()
    for index, char in enumerate(text):
        if char in ".:、．":
            prefix = text[:index]
            if prefix.isdigit() and index + 1 < len(text):
                return text[index + 1 :].strip()
            break
    return None


def _item_from_text(text: str) -> BoardItem:
    for separator in ("：", ":"):
        if separator in text:
            title, body = text.split(separator, 1)
            return BoardItem(title=title.strip(), body=body.strip())
    return BoardItem(title=text.strip(), body="")


class AnswerBoardSplitter:
    """從模型字串流切出口語文字；看板標記之後的內容不送入 TTS。"""

    def __init__(self) -> None:
        self._buffer = ""
        self._in_board = False
        self._board_raw = ""

    def feed(self, chunk: str) -> list[str]:
        if not chunk:
            return []
        if self._in_board:
            self._board_raw += chunk
            return []
        self._buffer += chunk
        marker_at = self._buffer.find(BOARD_START)
        if marker_at == -1:
            spoken, held = _hold_marker_prefix(self._buffer)
            self._buffer = held
            return [spoken] if spoken else []
        spoken = self._buffer[:marker_at]
        self._board_raw = self._buffer[marker_at + len(BOARD_START) :]
        self._buffer = ""
        self._in_board = True
        return [spoken] if spoken else []

    def flush(self) -> tuple[str, Optional[BoardPayload]]:
        if self._in_board:
            self._board_raw += self._buffer
            self._buffer = ""
            raw = self._board_raw
            end_at = raw.find(BOARD_END)
            if end_at != -1:
                raw = raw[:end_at]
            return "", parse_board_block(raw)
        leftover = self._buffer
        self._buffer = ""
        return leftover, None
