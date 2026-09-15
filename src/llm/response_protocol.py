# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Streaming response protocol parser, thinking suppression, and board validation.

Provides streaming separation of conversational speech and visual board JSON,
with robust stateful suppression of <think>...</think> tags across chunk boundaries.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Generator, Optional

from src.llm.router import ReplyMode

logger = logging.getLogger(__name__)

TAG_SPEECH = "[[SPEECH]]"
TAG_BOARD = "[[BOARD_JSON]]"
TAG_END = "[[END]]"
TAG_MODE_SIMPLE = "[[MODE:SIMPLE]]"
TAG_MODE_BOARD = "[[MODE:BOARD]]"
TAG_MODE_SIMPLE_ZH = "模式：簡答"
TAG_MODE_BOARD_ZH = "模式：看板"
TAG_SPEECH_ZH = "口語："
TAG_BOARD_ZH = "資料："
THINK_OPEN = "<think>"
THINK_CLOSE = "</think>"
THINK_TAG_PAIRS = (
    ("<think>", "</think>"),
    ("<thought>", "</thought>"),
    ("<|thought|>", "</|thought|>"),
    ("<thinking>", "</thinking>"),
    ("<|tool_call_start|>[think(", "<|tool_call_end|>"),
    ("[think(", ")]"),
)


@dataclass
class BoardItem:
    """A single item inside an answer board."""

    title: str
    content: str
    subtitle: Optional[str] = None
    badge: Optional[str] = None

    @property
    def body(self) -> str:
        """Backward-compatibility alias for body/content."""
        return self.content


@dataclass
class BoardPayload:
    """Structured data for an answer board."""

    title: str
    summary: Optional[str] = None
    items: list[BoardItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "items": [
                {
                    "title": item.title,
                    "content": item.content,
                    "body": item.content,
                    **({"subtitle": item.subtitle} if item.subtitle else {}),
                    **({"badge": item.badge} if item.badge else {}),
                }
                for item in self.items
            ],
        }


@dataclass
class SessionBoardContext:
    """Recent board state retained per session for follow-up queries."""

    turn_id: str
    title: str
    summary: Optional[str]
    items: list[BoardItem]
    created_at: float = field(default_factory=time.time)


def clean_speech_text(text: str, is_board_mode: bool = False) -> str:
    """Clean spoken text by stripping tool-call syntax, protocol tags, and board markers."""
    if not text:
        return ""
    # Strip tool-call tags and reasoning
    text = re.sub(r"<\|tool_call_start\|>.*?<\|tool_call_end\|>", "", text, flags=re.DOTALL)
    text = re.sub(r"<\|tool_call_start\|>.*", "", text)
    text = re.sub(r"<\|tool_call_end\|>", "", text)
    text = re.sub(r"\[(?:BOARD|think|thought)\(.*?\)?\]", "", text, flags=re.DOTALL)

    # Strip mode markers (both single and double brackets)
    text = re.sub(r"\[{1,2}\s*MODE\s*:\s*(?:SIMPLE|BOARD)\s*\]{1,2}", "", text, flags=re.IGNORECASE)
    text = re.sub(r"模式\s*[:：]\s*(?:簡答|看板)", "", text)

    # Track if text started with an open-bracket speech tag like [speech: ...
    had_bracket_speech = bool(re.search(r"\[{1,2}\s*(?:SPEECH|speech)\s*:\s*", text, flags=re.IGNORECASE))

    # Strip speech markers
    text = re.sub(r"\[{1,2}\s*/?\s*(?:SPEECH|speech)(?::\s*)?\]{1,2}", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[{1,2}\s*(?:SPEECH|speech)\s*:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?i)(?:^|[\r\n]+)\s*SPEECH\s*:\s*", "\n", text)
    text = re.sub(r"(?:^|[\r\n]+)\s*口語\s*[:：]\s*", "\n", text)

    # Strip board markers
    text = re.sub(r"\[{1,2}\s*/?\s*BOARD(?:_JSON)?(?::\s*)?\]{1,2}", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[{1,2}\s*BOARD(?:_JSON)?\s*:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?i)(?:^|[\r\n]+)\s*BOARD(?:_JSON)?\s*:\s*", "\n", text)
    text = re.sub(r"看板(?:資料)?\s*[:：]", "", text)
    text = re.sub(r"資料\s*[:：]", "", text)

    # Strip end markers
    text = re.sub(r"\[{1,2}\s*/?\s*END\s*\]{1,2}", "", text, flags=re.IGNORECASE)

    # Cut off before raw JSON or markdown JSON fence in ANY mode (speech must never contain JSON)
    json_match = re.search(r'(?:```(?:json)?\s*)?[\r\n]+\s*\{(?:\s*"title"|\s*"items"|\s*"summary")', text, flags=re.IGNORECASE)
    if json_match:
        text = text[:json_match.start()]

    # If had [speech: ... and text ends with ], strip the matching ]
    if had_bracket_speech:
        r_text = text.rstrip()
        while r_text.endswith("]") and r_text.count("]") > r_text.count("["):
            r_text = r_text[:-1].rstrip()
        text = r_text

    if is_board_mode:
        # Strip markdown bullets from speech so speech remains a concise overview
        list_match = re.search(r'[\r\n]+\s*(?:[-*]|\d+\.)\s+', text)
        if list_match:
            text = text[:list_match.start()]

    return text


class ThinkFilter:
    """Stateful stream filter that suppresses thinking/reasoning blocks.

    Handles opening and closing tags that may be split arbitrarily across chunks
    (e.g. '<th' + 'ink>', '</thi' + 'nk>').
    """

    def __init__(self) -> None:
        self._in_think = False
        self._active_close = ""
        self._buffer = ""

    def feed(self, chunk: str) -> list[str]:
        if not chunk:
            return []

        self._buffer += chunk
        out: list[str] = []

        while self._buffer:
            if not self._in_think:
                # Find earliest matching open tag
                found = []
                for open_tag, close_tag in THINK_TAG_PAIRS:
                    pos = self._buffer.find(open_tag)
                    if pos != -1:
                        found.append((pos, open_tag, close_tag))
                if found:
                    pos, open_tag, close_tag = min(found, key=lambda x: x[0])
                    pre = self._buffer[:pos]
                    if pre:
                        out.append(pre)
                    self._buffer = self._buffer[pos + len(open_tag) :]
                    self._in_think = True
                    self._active_close = close_tag
                    continue

                # Buffer might end with a partial prefix of an open tag
                max_overlap = 0
                for open_tag, _ in THINK_TAG_PAIRS:
                    overlap = self._prefix_overlap(self._buffer, open_tag)
                    if overlap > max_overlap:
                        max_overlap = overlap

                if max_overlap > 0:
                    emit_len = len(self._buffer) - max_overlap
                    if emit_len > 0:
                        out.append(self._buffer[:emit_len])
                        self._buffer = self._buffer[emit_len:]
                    break
                else:
                    out.append(self._buffer)
                    self._buffer = ""
                    break
            else:
                # Inside thinking block: discard text until active close tag is found
                pos = self._buffer.find(self._active_close)
                if pos != -1:
                    self._buffer = self._buffer[pos + len(self._active_close) :]
                    self._in_think = False
                    self._active_close = ""
                    continue

                # Buffer might end with a partial prefix of active close tag
                hold_len = self._prefix_overlap(self._buffer, self._active_close)
                if hold_len > 0:
                    self._buffer = self._buffer[-hold_len:]
                else:
                    self._buffer = ""
                break

        return [s for s in out if s]

    def flush(self) -> list[str]:
        """Flush any held characters at the end of the stream."""
        out: list[str] = []
        if not self._in_think and self._buffer:
            out.append(self._buffer)
        self._buffer = ""
        self._in_think = False
        self._active_close = ""
        return [s for s in out if s]

    @staticmethod
    def _prefix_overlap(text: str, target: str) -> int:
        """Returns the length of the longest suffix of `text` that is a prefix of `target`."""
        max_k = min(len(text), len(target) - 1)
        for k in range(max_k, 0, -1):
            if target.startswith(text[-k:]):
                return k
        return 0


class ParserState(str, Enum):
    WAIT_SPEECH = "wait_speech"
    IN_SPEECH = "in_speech"
    WAIT_BOARD = "wait_board"
    IN_BOARD = "in_board"
    DONE = "done"


class ResponseProtocolParser:
    """Streaming state machine for parsing speech and board channels.

    Guarantees:
    1. Speech chunks are emitted immediately (zero waiting for the board).
    2. Thinking tags are suppressed across chunk boundaries.
    3. Protocol tags ([[SPEECH]], [[BOARD_JSON]], [[END]]) never leak into speech.
    4. Board JSON is buffered separately; complete item objects may be emitted
       incrementally while the final payload is still being assembled.
    5. Malformed board JSON logs a warning without crashing or discarding speech.
    """

    def __init__(
        self,
        mode: ReplyMode = ReplyMode.SIMPLE,
        *,
        max_items: int = 8,
        on_speech: Optional[Callable[[str], None]] = None,
        on_board: Optional[Callable[[BoardPayload], None]] = None,
        on_mode: Optional[Callable[[ReplyMode], None]] = None,
        on_board_item: Optional[Callable[[int, BoardItem], None]] = None,
    ) -> None:
        self.mode = mode
        self.max_items = max_items
        self.on_speech = on_speech
        self.on_board = on_board
        self.on_mode = on_mode
        self.on_board_item = on_board_item

        self._think_filter = ThinkFilter()
        self._state = ParserState.WAIT_SPEECH if mode in (ReplyMode.BOARD, ReplyMode.AUTO) else ParserState.IN_SPEECH
        self._buffer = ""
        self._board_buffer = ""
        self._speech_accumulator = ""
        self._board_payload: Optional[BoardPayload] = None
        self._protocol_wrapped = mode == ReplyMode.BOARD
        self._chinese_protocol = False
        self._partial_item_indices: set[int] = set()
        self._collected_items: list[BoardItem] = []

    @property
    def speech_text(self) -> str:
        return self._speech_accumulator

    @property
    def board_payload(self) -> Optional[BoardPayload]:
        return self._board_payload

    def feed(self, chunk: str) -> list[str]:
        """Feed a raw LLM chunk. Returns a list of speech chunks to output."""
        clean_chunks = self._think_filter.feed(chunk)
        if not clean_chunks:
            return []

        speech_outputs: list[str] = []
        for clean_text in clean_chunks:
            if self.mode == ReplyMode.AUTO:
                outputs = self._process_auto_chunk(clean_text)
                speech_outputs.extend(outputs)
            elif self.mode == ReplyMode.SIMPLE:
                if self._protocol_wrapped:
                    speech_outputs.extend(self._process_simple_wrapped_chunk(clean_text))
                else:
                    clean_text = clean_speech_text(clean_text, is_board_mode=False)
                    if clean_text:
                        self._speech_accumulator += clean_text
                        speech_outputs.append(clean_text)
                        if self.on_speech:
                            self.on_speech(clean_text)
            else:
                outputs = self._process_board_mode_chunk(clean_text)
                speech_outputs.extend(outputs)

        return speech_outputs

    def _notify_mode(self) -> None:
        if callable(self.on_mode) and self.mode in (ReplyMode.SIMPLE, ReplyMode.BOARD):
            self.on_mode(self.mode)

    def _process_auto_chunk(self, chunk: str) -> list[str]:
        """Resolve one mode marker before delegating to the fixed parser."""
        self._buffer += chunk
        candidates = (
            (TAG_MODE_SIMPLE, ReplyMode.SIMPLE),
            (TAG_MODE_BOARD, ReplyMode.BOARD),
            ("[MODE:SIMPLE]", ReplyMode.SIMPLE),
            ("[MODE:BOARD]", ReplyMode.BOARD),
            ("[mode:simple]", ReplyMode.SIMPLE),
            ("[mode:board]", ReplyMode.BOARD),
            (TAG_MODE_SIMPLE_ZH, ReplyMode.SIMPLE),
            (TAG_MODE_BOARD_ZH, ReplyMode.BOARD),
            ("模式:看板", ReplyMode.BOARD),
            ("模式:簡答", ReplyMode.SIMPLE),
            ("<|tool_call_start|>[BOARD", ReplyMode.BOARD),
            ("[BOARD(", ReplyMode.BOARD),
            ("BOARD(JSON=", ReplyMode.BOARD),
            ("BOARD(items=", ReplyMode.BOARD),
            ("BOARD(MODE=", ReplyMode.BOARD),
        )
        found = [(self._buffer.find(tag), tag, mode) for tag, mode in candidates if self._buffer.find(tag) >= 0]
        if found:
            _, tag, mode = min(found, key=lambda item: item[0])
            self.mode = mode
            self._state = ParserState.WAIT_SPEECH
            self._protocol_wrapped = True
            self._chinese_protocol = tag in (TAG_MODE_SIMPLE_ZH, TAG_MODE_BOARD_ZH, "模式:看板", "模式:簡答")
            self._notify_mode()
            if tag in ("<|tool_call_start|>[BOARD", "[BOARD(", "BOARD(JSON=", "BOARD(items=", "BOARD(MODE="):
                text = self._buffer
                self._buffer = ""
                return self._process_board_mode_chunk(text)
            self._buffer = self._buffer[self._buffer.find(tag) + len(tag):].lstrip("\r\n ")
            if not self._buffer:
                return []
            if mode == ReplyMode.SIMPLE:
                text = self._buffer
                self._buffer = ""
                return self._process_simple_wrapped_chunk(text)
            text = self._buffer
            self._buffer = ""
            return self._process_board_mode_chunk(text)

        # AUTO output is a machine-readable envelope. Keep an unmarked answer
        # buffered until flush so a late BOARD marker or JSON object can never
        # be committed to speech as plain text.
        return []

    def _process_simple_wrapped_chunk(self, chunk: str) -> list[str]:
        """Parse the fixed speech/end framing for an AUTO SIMPLE answer."""
        self._buffer += chunk
        if self._state == ParserState.WAIT_SPEECH:
            speech_m = re.search(
                r"(\[{1,2}\s*(?:SPEECH|speech)(?::\s*)?\]{1,2}|\[{1,2}\s*(?:SPEECH|speech)\s*:\s*|(?:^|[\r\n]+)\s*SPEECH\s*:\s*|(?:^|[\r\n]+)\s*口語\s*[:：]\s*)",
                self._buffer,
                flags=re.IGNORECASE,
            )
            if speech_m:
                self._buffer = self._buffer[speech_m.end():].lstrip("\r\n ")
                self._state = ParserState.IN_SPEECH
            else:
                # llama.cpp commonly emits the newline after MODE as its own
                # SSE chunk. It is envelope whitespace, not spoken content.
                if not self._buffer.strip():
                    return []
                speech_overlap = max(
                    ThinkFilter._prefix_overlap(self._buffer, TAG_SPEECH),
                    ThinkFilter._prefix_overlap(self._buffer, "[SPEECH]"),
                    ThinkFilter._prefix_overlap(self._buffer, "[speech]"),
                    ThinkFilter._prefix_overlap(self._buffer, "[speech:"),
                    ThinkFilter._prefix_overlap(self._buffer, TAG_SPEECH_ZH),
                    ThinkFilter._prefix_overlap(self._buffer, "口語:"),
                )
                if speech_overlap > 0:
                    self._buffer = self._buffer[-speech_overlap:]
                    return []
                self._state = ParserState.IN_SPEECH
        if self._state == ParserState.DONE:
            self._buffer = ""
            return []
        end_m = re.search(
            r"(\[{1,2}\s*/?\s*END\s*\]{1,2}|\[{1,2}\s*/\s*(?:SPEECH|speech)\s*\]{1,2})",
            self._buffer,
            flags=re.IGNORECASE,
        )
        if end_m:
            text = self._buffer[:end_m.start()]
            self._buffer = self._buffer[end_m.end():]
            self._state = ParserState.DONE
        else:
            overlap = max(
                ThinkFilter._prefix_overlap(self._buffer, TAG_END),
                ThinkFilter._prefix_overlap(self._buffer, "[END]"),
            )
            if overlap:
                text = self._buffer[:-overlap]
                self._buffer = self._buffer[-overlap:]
            else:
                text, self._buffer = self._buffer, ""
        if not text:
            return []
        clean_text = clean_speech_text(text, is_board_mode=False)
        if not clean_text:
            return []
        self._speech_accumulator += clean_text
        if self.on_speech:
            self.on_speech(clean_text)
        return [clean_text]

    def _process_board_mode_chunk(self, chunk: str) -> list[str]:
        self._buffer += chunk
        speech_outputs: list[str] = []
        speech_tag = TAG_SPEECH_ZH if self._chinese_protocol else TAG_SPEECH
        board_tag = TAG_BOARD_ZH if self._chinese_protocol else TAG_BOARD

        while self._buffer:
            if self._state == ParserState.WAIT_SPEECH:
                # Check for tool-call SPEECH attribute
                speech_m = re.search(r"SPEECH\s*=\s*(['\"])(.*?)\1", self._buffer, flags=re.DOTALL)
                if speech_m:
                    speech_text = clean_speech_text(speech_m.group(2), is_board_mode=True)
                    if speech_text:
                        self._speech_accumulator += speech_text
                        speech_outputs.append(speech_text)
                        if self.on_speech:
                            self.on_speech(speech_text)
                    self._buffer = self._buffer[speech_m.end():]
                    self._state = ParserState.IN_BOARD
                    continue

                if self._buffer.lstrip().startswith(("{", "```", "[BOARD", "<|tool_call_start|>")):
                    self._state = ParserState.IN_BOARD
                    continue

                pos = self._buffer.find(speech_tag)
                if pos != -1:
                    pre = self._buffer[:pos]
                    if pre.strip():
                        clean_pre = clean_speech_text(pre, is_board_mode=True)
                        if clean_pre:
                            self._speech_accumulator += clean_pre
                            speech_outputs.append(clean_pre)
                            if self.on_speech:
                                self.on_speech(clean_pre)
                    self._buffer = self._buffer[pos + len(speech_tag):].lstrip("\r\n ")
                    self._state = ParserState.IN_SPEECH
                    continue

                tag_m = re.search(
                    r"(\[{1,2}\s*(?:SPEECH|speech)(?::\s*)?\]{1,2}|\[{1,2}\s*(?:SPEECH|speech)\s*:\s*|(?:^|[\r\n]+)\s*SPEECH\s*:\s*|(?:^|[\r\n]+)\s*口語\s*[:：]\s*)",
                    self._buffer,
                    flags=re.IGNORECASE,
                )
                if tag_m:
                    pre = self._buffer[:tag_m.start()]
                    if pre.strip():
                        clean_pre = clean_speech_text(pre, is_board_mode=True)
                        if clean_pre:
                            self._speech_accumulator += clean_pre
                            speech_outputs.append(clean_pre)
                            if self.on_speech:
                                self.on_speech(clean_pre)
                    self._buffer = self._buffer[tag_m.end():].lstrip("\r\n ")
                    self._state = ParserState.IN_SPEECH
                    continue

                # Check if buffer could be a prefix of speech tag
                overlap = max(
                    ThinkFilter._prefix_overlap(self._buffer, speech_tag),
                    ThinkFilter._prefix_overlap(self._buffer, TAG_SPEECH),
                    ThinkFilter._prefix_overlap(self._buffer, "[SPEECH]"),
                    ThinkFilter._prefix_overlap(self._buffer, "[speech]"),
                    ThinkFilter._prefix_overlap(self._buffer, "[speech:"),
                    ThinkFilter._prefix_overlap(self._buffer, TAG_SPEECH_ZH),
                    ThinkFilter._prefix_overlap(self._buffer, "口語:"),
                )
                if overlap > 0:
                    pre = self._buffer[:-overlap]
                    if pre.strip():
                        self._state = ParserState.IN_SPEECH
                        clean_pre = clean_speech_text(pre, is_board_mode=True)
                        if clean_pre:
                            self._speech_accumulator += clean_pre
                            speech_outputs.append(clean_pre)
                            if self.on_speech:
                                self.on_speech(clean_pre)
                        self._buffer = self._buffer[-overlap:]
                    break
                else:
                    if self._buffer.strip():
                        self._state = ParserState.IN_SPEECH
                        text = self._buffer
                        self._buffer = ""
                        clean_text = clean_speech_text(text, is_board_mode=True)
                        if clean_text:
                            self._speech_accumulator += clean_text
                            speech_outputs.append(clean_text)
                            if self.on_speech:
                                self.on_speech(clean_text)
                    else:
                        break

            elif self._state == ParserState.IN_SPEECH:
                pos = self._buffer.find(board_tag)
                board_match_len = len(board_tag)
                if pos == -1:
                    alt_pattern = re.compile(
                        r"(\[{1,2}\s*BOARD(?:_JSON)?(?::\s*)?\]{1,2}|看板(?:資料)?\s*[:：]|(?:^|[\r\n]+)\s*資料\s*[:：])|(```(?:json)?\s*\{|[\r\n]*\s*\{\s*\"(?:title|items)\"|<\|tool_call_start\|>\[BOARD|\[BOARD\(|[\r\n]+\s*(?:[-*]|\d+\.)\s+)",
                        re.IGNORECASE,
                    )
                    m = alt_pattern.search(self._buffer)
                    if m:
                        pos = m.start()
                        board_match_len = len(m.group(1)) if m.group(1) else 0

                if pos != -1:
                    speech_part = self._buffer[:pos]
                    clean_speech = clean_speech_text(speech_part, is_board_mode=True)
                    if clean_speech:
                        self._speech_accumulator += clean_speech
                        speech_outputs.append(clean_speech)
                        if self.on_speech:
                            self.on_speech(clean_speech)
                    self._buffer = self._buffer[pos + board_match_len:].lstrip("\r\n ")
                    self._state = ParserState.IN_BOARD
                    continue

                # Check if buffer ends with a prefix of board tag
                overlap = max(
                    ThinkFilter._prefix_overlap(self._buffer, board_tag),
                    ThinkFilter._prefix_overlap(self._buffer, TAG_BOARD),
                    ThinkFilter._prefix_overlap(self._buffer, "[BOARD_JSON]"),
                    ThinkFilter._prefix_overlap(self._buffer, "[BOARD]"),
                    ThinkFilter._prefix_overlap(self._buffer, TAG_BOARD_ZH),
                    ThinkFilter._prefix_overlap(self._buffer, "看板:"),
                    ThinkFilter._prefix_overlap(self._buffer, "```json"),
                    ThinkFilter._prefix_overlap(self._buffer, "<|tool_call_start|>"),
                )
                if overlap > 0:
                    emit_len = len(self._buffer) - overlap
                    if emit_len > 0:
                        part = self._buffer[:emit_len]
                        clean_part = clean_speech_text(part, is_board_mode=True)
                        if clean_part:
                            self._speech_accumulator += clean_part
                            speech_outputs.append(clean_part)
                            if self.on_speech:
                                self.on_speech(clean_part)
                        self._buffer = self._buffer[emit_len:]
                    break
                else:
                    part = self._buffer
                    self._buffer = ""
                    clean_part = clean_speech_text(part, is_board_mode=True)
                    if clean_part:
                        self._speech_accumulator += clean_part
                        speech_outputs.append(clean_part)
                        if self.on_speech:
                            self.on_speech(clean_part)
                    break

            elif self._state == ParserState.IN_BOARD:
                pos = self._buffer.find(TAG_END)
                end_len = len(TAG_END)
                if pos == -1:
                    alt_end = re.search(
                        r"(?:\[{1,2}\s*/?\s*END\s*\]{1,2}|<\|tool_call_end\|>|\]\)|```\s*$)",
                        self._buffer,
                        flags=re.IGNORECASE,
                    )
                    if alt_end:
                        pos = alt_end.start()
                        end_len = len(alt_end.group(0))

                if pos != -1:
                    board_part = self._buffer[:pos]
                    self._board_buffer += board_part
                    self._emit_partial_items()
                    self._buffer = self._buffer[pos + end_len:].lstrip("\r\n ")
                    self._state = ParserState.DONE
                    self._parse_and_emit_board()
                    continue

                overlap = max(
                    ThinkFilter._prefix_overlap(self._buffer, TAG_END),
                    ThinkFilter._prefix_overlap(self._buffer, "[END]"),
                    ThinkFilter._prefix_overlap(self._buffer, "<|tool_call_end|>"),
                    ThinkFilter._prefix_overlap(self._buffer, "])"),
                )
                if overlap > 0:
                    emit_len = len(self._buffer) - overlap
                    if emit_len > 0:
                        self._board_buffer += self._buffer[:emit_len]
                        self._emit_partial_items()
                        self._buffer = self._buffer[emit_len:]
                    break
                else:
                    self._board_buffer += self._buffer
                    self._emit_partial_items()
                    self._buffer = ""
                    break

            elif self._state == ParserState.DONE:
                self._buffer = ""
                break

        return speech_outputs

    def flush(self) -> tuple[list[str], Optional[BoardPayload]]:
        """Flush any held buffers and finalize board JSON parsing."""
        clean_chunks = self._think_filter.flush()
        speech_outputs: list[str] = []

        if self.mode == ReplyMode.AUTO:
            self._buffer += "".join(clean_chunks)
            raw_board = re.search(
                r'(?:```(?:json)?\s*)?\{\s*"(?:title|items|summary)"',
                self._buffer,
                flags=re.IGNORECASE,
            )
            if raw_board:
                self.mode = ReplyMode.BOARD
                self._state = ParserState.IN_SPEECH
                self._protocol_wrapped = True
                self._notify_mode()
                speech_outputs.extend(self._process_board_mode_chunk(""))
            else:
                self.mode = ReplyMode.SIMPLE
                self._state = ParserState.IN_SPEECH
                self._notify_mode()
                if self._buffer:
                    text, self._buffer = self._buffer, ""
                    clean_text = clean_speech_text(text, is_board_mode=False)
                    if clean_text:
                        self._speech_accumulator += clean_text
                        speech_outputs.append(clean_text)
                        if self.on_speech:
                            self.on_speech(clean_text)
                return speech_outputs, self._board_payload

        for clean_text in clean_chunks:
            if self.mode == ReplyMode.SIMPLE:
                if self._protocol_wrapped:
                    speech_outputs.extend(self._process_simple_wrapped_chunk(clean_text))
                    continue
                clean_simple = clean_speech_text(clean_text, is_board_mode=False)
                if clean_simple:
                    self._speech_accumulator += clean_simple
                    speech_outputs.append(clean_simple)
                    if self.on_speech:
                        self.on_speech(clean_simple)
            else:
                outputs = self._process_board_mode_chunk(clean_text)
                speech_outputs.extend(outputs)

        if self.mode == ReplyMode.BOARD:
            if self._state == ParserState.IN_SPEECH and self._buffer:
                alt_pattern = re.compile(
                    r"(?:```(?:json)?\s*\{|[\r\n]+\s*\{\s*\"(?:title|items)\"|<\|tool_call_start\|>\[BOARD|\[BOARD\()",
                    re.IGNORECASE,
                )
                m = alt_pattern.search(self._buffer)
                if m:
                    speech_part = self._buffer[: m.start()]
                    clean_speech = clean_speech_text(speech_part, is_board_mode=True)
                    if clean_speech:
                        self._speech_accumulator += clean_speech
                        speech_outputs.append(clean_speech)
                        if self.on_speech:
                            self.on_speech(clean_speech)
                    self._board_buffer += self._buffer[m.start() :]
                    self._buffer = ""
                    self._state = ParserState.DONE
                    self._emit_partial_items()
                    self._parse_and_emit_board()
                else:
                    markdown_items = self._extract_markdown_board_items(self._buffer)
                    if markdown_items:
                        list_m = re.search(r"[\r\n]+\s*(?:[-*]|\d+\.)\s+", self._buffer)
                        speech_part = self._buffer[: list_m.start()] if list_m else ""
                        clean_speech = clean_speech_text(speech_part, is_board_mode=True)
                        if clean_speech:
                            self._speech_accumulator += clean_speech
                            speech_outputs.append(clean_speech)
                            if self.on_speech:
                                self.on_speech(clean_speech)
                        self._board_payload = BoardPayload(
                            title="看板回覆",
                            summary=None,
                            items=markdown_items[: self.max_items],
                        )
                        if self.on_board:
                            self.on_board(self._board_payload)
                    else:
                        leftover = clean_speech_text(self._buffer, is_board_mode=True)
                        self._buffer = ""
                        if leftover:
                            self._speech_accumulator += leftover
                            speech_outputs.append(leftover)
                            if self.on_speech:
                                self.on_speech(leftover)
            elif self._state == ParserState.IN_BOARD:
                if self._buffer:
                    self._board_buffer += self._buffer
                    self._buffer = ""
                self._emit_partial_items()
                self._state = ParserState.DONE
                self._parse_and_emit_board()

        return speech_outputs, self._board_payload

    def _parse_and_emit_board(self) -> None:
        raw = self._board_buffer.strip()
        if not raw:
            return

        # Check for tool-call envelope e.g. BOARD(...)
        tool_call_m = re.search(r"BOARD\s*\((?:.*?)BOARD_JSON\s*=\s*(['\"])(.*?)\1", raw, flags=re.DOTALL)
        if tool_call_m:
            raw = tool_call_m.group(2).encode("utf-8").decode("unicode_escape", errors="replace")
        else:
            tool_json_m = re.search(r"BOARD\s*\((?:.*?)JSON\s*=\s*(['\"])(.*?)\1", raw, flags=re.DOTALL)
            if tool_json_m:
                raw = tool_json_m.group(2).encode("utf-8").decode("unicode_escape", errors="replace")

        # Strip markdown fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
        raw = raw.strip()

        parsed = None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("board_parse_success=false initial_error=%s attempting repair", exc)
            repaired = raw
            repaired = re.sub(r"\]\s*\]\s*\}", "]}", repaired)
            repaired = re.sub(r",\s*([\]\}])", r"\1", repaired)
            try:
                parsed = json.loads(repaired)
            except Exception:
                pass

        if isinstance(parsed, dict):
            title = str(parsed.get("title") or "看板回覆").strip()
            summary = parsed.get("summary")
            if summary is not None:
                summary = str(summary).strip() or None

            raw_items = parsed.get("items") or []
            if not isinstance(raw_items, list):
                raw_items = []

            items: list[BoardItem] = []
            for entry in raw_items:
                item = self._coerce_board_item(entry)
                if item is not None:
                    items.append(item)

            if len(items) > self.max_items:
                items = items[: self.max_items]

            if items:
                payload = BoardPayload(title=title, summary=summary, items=items)
                self._board_payload = payload
                logger.info("board_parse_success=true board_items=%d title=%r", len(items), title)
                if self.on_board:
                    self.on_board(payload)
                return

        # Fallback 1: use items collected during streaming
        if self._collected_items:
            title_m = re.search(r'"title"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', raw)
            title = title_m.group(1).strip() if title_m else "看板回覆"
            items = self._collected_items[: self.max_items]
            payload = BoardPayload(title=title, summary=None, items=items)
            self._board_payload = payload
            logger.info("board_parse_success=true fallback=collected_items count=%d", len(items))
            if self.on_board:
                self.on_board(payload)
            return

        # Fallback 2: extract markdown bullet points
        markdown_items = self._extract_markdown_board_items(raw)
        if markdown_items:
            items = markdown_items[: self.max_items]
            payload = BoardPayload(title="看板回覆", summary=None, items=items)
            self._board_payload = payload
            logger.info("board_parse_success=true fallback=markdown_items count=%d", len(items))
            if self.on_board:
                self.on_board(payload)
            return

        logger.warning("board_parse_success=false reason=could_not_parse_items raw_length=%d", len(raw))

    def _emit_partial_items(self) -> None:
        """Emit only fully decoded items while the enclosing JSON is streaming."""
        match = re.search(r'"items"\s*:\s*\[', self._board_buffer)
        if not match:
            return
        cursor = match.end()
        decoder = json.JSONDecoder()
        display_index = 0
        while cursor < len(self._board_buffer):
            while cursor < len(self._board_buffer) and self._board_buffer[cursor] in " \r\n\t,":
                cursor += 1
            if cursor >= len(self._board_buffer) or self._board_buffer[cursor] == "]":
                break
            if display_index >= self.max_items:
                break
            try:
                value, end = decoder.raw_decode(self._board_buffer, cursor)
            except json.JSONDecodeError:
                break
            cursor = end
            item = self._coerce_board_item(value)
            if item is not None:
                if display_index not in self._partial_item_indices:
                    self._partial_item_indices.add(display_index)
                    self._collected_items.append(item)
                    if callable(self.on_board_item):
                        try:
                            self.on_board_item(display_index, item)
                        except Exception:
                            logger.exception("board item callback failed index=%s", display_index)
                display_index += 1

    @staticmethod
    def _extract_markdown_board_items(text: str) -> list[BoardItem]:
        items: list[BoardItem] = []
        pattern = re.compile(
            r"^(?:[-*]|\d+\.)\s*(?:\*\*(.*?)\*\*|(.*?))(?:\s*[:：]\s*|\s*——\s*|\s+)(.*)$",
            re.MULTILINE,
        )
        for m in pattern.finditer(text):
            title = (m.group(1) or m.group(2) or "").strip()
            content = (m.group(3) or "").strip()
            if title and content:
                items.append(BoardItem(title=title, content=content))
        return items

    @staticmethod
    def _coerce_board_item(value: Any) -> Optional[BoardItem]:
        if isinstance(value, str) and value.strip():
            return BoardItem(title=value.strip(), content="")
        if not isinstance(value, dict):
            return None
        title = str(value.get("title") or "").strip()
        content = str(value.get("content") or value.get("body") or value.get("description") or "").strip()
        if not title and not content:
            return None
        return BoardItem(
            title=title or content,
            content=content,
            subtitle=str(value.get("subtitle")).strip() if value.get("subtitle") else None,
            badge=str(value.get("badge")).strip() if value.get("badge") else None,
        )
