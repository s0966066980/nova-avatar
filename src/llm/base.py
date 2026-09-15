# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""LLM 基類模組"""

from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable, Generator, Optional
from uuid import uuid4

from src.llm.answer_board import AnswerBoardSplitter, with_board_instruction
from src.llm.prompts import compose_system_prompt
from src.llm.response_protocol import (
    BoardItem,
    BoardPayload,
    ResponseProtocolParser,
    SessionBoardContext,
)
from src.llm.rules import snapshot_from_config
from src.llm.router import ReplyMode
from src.llm.text_normalizer import (
    normalize_assistant_identity,
    normalize_output_text,
    strip_unsolicited_self_introduction,
)
from src.server.reply_streaming.fragmenter import SemanticFragmenter
from src.utils.logging import logger

if TYPE_CHECKING:
    from src.avatars.base import BaseAvatar


DEFAULT_SYSTEM_PROMPT = 'You are a helpful assistant.'
DEFAULT_RESPONSE_MAX_CHARS = 120
MIN_RESPONSE_MAX_CHARS = 20
MAX_RESPONSE_MAX_CHARS = 2000
# 只在完整句尾切給 TTS。逗號與冒號屬於句內停頓，拆開合成會重置韻律，
# 也會讓 Avatar 在相鄰 TTS 請求之間提前填入靜音幀。
SENTENCE_DELIMITERS = ".!?;。！？；"
MIN_SENTENCE_LENGTH = 24


def validate_response_max_chars(value) -> int:
    """驗證並正規化使用者可調整的約略回覆字數。"""
    if isinstance(value, bool):
        raise ValueError("回覆字數必須是整數")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("回覆字數必須是整數") from exc
    if isinstance(value, float) and not value.is_integer():
        raise ValueError("回覆字數必須是整數")
    if not MIN_RESPONSE_MAX_CHARS <= normalized <= MAX_RESPONSE_MAX_CHARS:
        raise ValueError(
            f"回覆字數必須介於 {MIN_RESPONSE_MAX_CHARS} 到 {MAX_RESPONSE_MAX_CHARS} 之間"
        )
    return normalized


def response_token_budget(max_chars: int) -> int:
    """Safety ceiling above the character target so the last sentence can finish."""
    estimated = max(64, math.ceil(max_chars * 2.5) + 32)
    return min(4096, estimated + 256)


def with_response_length_instruction(system_prompt: str, max_chars: int) -> str:
    """加入隱藏的柔性長度指令，不污染使用者可編輯的 Prompt。"""
    prompt = (system_prompt or DEFAULT_SYSTEM_PROMPT).rstrip()
    length_prompt = (
        f"{prompt}\n\n【回覆長度】每次回答必須是結構完整的短答，總長度約 {max_chars} 個字。"
        "先在限制內把話說完；不要開一個無法在限制內結束的長句或列表。"
        "禁止在句子或條目中途停止。"
    )
    return with_board_instruction(length_prompt)


def load_system_prompt(config=None) -> str:
    """取得控制台 profile 的 Prompt；只保留中性的技術 fallback。"""
    llm_config = getattr(config, "llm", None) if config is not None else None
    profile = getattr(llm_config, "assistant_profile", None)
    configured_prompt = getattr(profile, "system_prompt", "") or ""
    if configured_prompt.strip():
        return configured_prompt.strip()
    # Phase-1 migration: read an existing config value once, but never persist it.
    legacy_prompt = getattr(llm_config, "system_prompt", "") or ""
    if legacy_prompt.strip():
        logger.warning("Using legacy llm.system_prompt; save Assistant Profile to migrate it")
        return legacy_prompt.strip()
    logger.warning("Assistant System Prompt is unset; using neutral technical fallback")
    return DEFAULT_SYSTEM_PROMPT


class TextStreamProcessor:
    """文本流處理器，負責分句和緩衝"""
    
    def __init__(self, delimiters: str = SENTENCE_DELIMITERS, min_length: int = MIN_SENTENCE_LENGTH):
        self.delimiters = delimiters
        self.min_length = min_length
        self.buffer = ""
    
    def process_chunk(self, text: str, callback) -> None:
        if not text:
            return
        
        # 以標點為分隔符，儘量保持語義完整再發給 TTS
        last_pos = 0
        for i, char in enumerate(text):
            if char in self.delimiters:
                sentence = self.buffer + text[last_pos:i + 1]
                last_pos = i + 1
                
                if len(sentence) >= self.min_length:
                    callback(sentence)
                    self.buffer = ""
                else:
                    self.buffer = sentence
        
        self.buffer += text[last_pos:]
    
    def flush(self, callback) -> None:
        if self.buffer:
            callback(self.buffer)
            self.buffer = ""


class BaseLLM(ABC):
    """所有 LLM 引擎的基類"""
    
    def __init__(self, config, parent: Optional["BaseAvatar"] = None):
        self.config = config
        self.parent = parent
        self.system_prompt = self._load_system_prompt()
        self._last_board: Optional[SessionBoardContext] = None
        self._pending_boards: dict[str, SessionBoardContext] = {}
        self._pending_board_receipts: dict[str, set[int]] = {}
    
    def _load_system_prompt(self) -> str:
        return load_system_prompt(self.config)

    def get_last_board(self) -> Optional[SessionBoardContext]:
        """Return the most recent board context for this LLM instance."""
        return self._last_board

    def set_last_board(self, board: Optional[SessionBoardContext]) -> None:
        """Store the most recent board context."""
        self._last_board = board
        if board is None:
            self._pending_boards.clear()
            self._pending_board_receipts.clear()

    def queue_board_for_display(self, board: SessionBoardContext) -> None:
        """Retain generated board content until a presenter confirms rendering it."""
        self._pending_boards[board.turn_id] = board
        self._publish_displayed_board(board.turn_id)

    def acknowledge_board_display(
        self,
        *,
        turn_id: str,
        board_id: str,
        item_index: int,
    ) -> bool:
        """Record one renderer receipt; only receipts become follow-up context."""
        if not turn_id or board_id != turn_id or item_index < 0:
            return False
        self._pending_board_receipts.setdefault(turn_id, set()).add(item_index)
        self._publish_displayed_board(turn_id)
        return True

    def _publish_displayed_board(self, turn_id: str) -> None:
        pending = self._pending_boards.get(turn_id)
        if pending is None:
            return
        received = self._pending_board_receipts.get(turn_id, set())
        displayed = [
            item for index, item in enumerate(pending.items) if index in received
        ]
        if not displayed:
            return
        self._last_board = SessionBoardContext(
            turn_id=pending.turn_id,
            title=pending.title,
            summary=pending.summary,
            items=displayed,
        )
    
    @abstractmethod
    def chat_stream(self, message: str, system_prompt: Optional[str] = None) -> Generator[str, None, None]:
        """流式呼叫 LLM，子類必須實現"""
        raise NotImplementedError("子類必須實現 chat_stream 方法")
    
    def generate_response(
        self,
        message: str,
        avatar_stream: Optional["BaseAvatar"] = None,
        *,
        stream_to_avatar: bool = True,
        datainfo: Optional[dict] = None,
        chunk_guard: Optional[Callable[[int], bool]] = None,
        defer_history_commit: bool = False,
        reply_mode: Optional[ReplyMode | str] = None,
    ) -> str:
        """生成完整響應並推送到 avatar"""
        start_time = time.perf_counter()
        pref_str = (
            reply_mode.value.lower()
            if isinstance(reply_mode, ReplyMode)
            else str(reply_mode or "").lower()
        )
        if reply_mode == ReplyMode.BOARD or pref_str in ("board", "replymode.board"):
            norm_mode = ReplyMode.BOARD
        elif (
            reply_mode == ReplyMode.SIMPLE
            or pref_str in ("simple", "replymode.simple")
            or (reply_mode is None and not callable((datainfo or {}).get("on_mode")))
        ):
            norm_mode = ReplyMode.SIMPLE
        else:
            norm_mode = ReplyMode.AUTO

        max_items = 8
        llm_cfg = getattr(self.config, "llm", None) if self.config is not None else None
        if llm_cfg is not None:
            board_cfg = getattr(llm_cfg, "board", None)
            if board_cfg is not None and hasattr(board_cfg, "max_items"):
                max_items = int(board_cfg.max_items)

        resp_chars = getattr(self, "response_max_chars", None)
        profile = getattr(llm_cfg, "assistant_profile", None)
        rules_snapshot = (datainfo or {}).get("rules_snapshot")
        if rules_snapshot is None:
            rules_snapshot = snapshot_from_config(self.config)
        composed_system_prompt = compose_system_prompt(
            self.system_prompt,
            reply_mode=norm_mode,
            response_max_chars=resp_chars,
            board_max_items=max_items,
            rules=rules_snapshot,
            displayed_board=self.get_last_board(),
            assistant_name=str(getattr(profile, "assistant_name", "") or ""),
            restriction_prompt=str(getattr(profile, "restriction_prompt", "") or ""),
        )

        semantic_stream = bool(
            stream_to_avatar
            and datainfo
            and datainfo.get("turn_id")
            and datainfo.get("generation") is not None
        )
        weak_min = int(
            getattr(
                getattr(self.config, "reply_streaming", None),
                "weak_min_chars",
                24,
            )
            or 24
        )
        soft_limit = int(
            getattr(
                getattr(self.config, "reply_streaming", None),
                "soft_limit_chars",
                72,
            )
            or 72
        )
        hard_limit = int(
            getattr(
                getattr(self.config, "reply_streaming", None),
                "hard_limit_chars",
                120,
            )
            or 120
        )
        strong_min = int(
            getattr(
                getattr(self.config, "reply_streaming", None),
                "strong_min_chars",
                1,
            )
            or 1
        )
        semantic_wait_seconds = float(
            getattr(
                getattr(self.config, "reply_streaming", None),
                "semantic_wait_seconds",
                5.0,
            )
            or 5.0
        )
        text_processor = (
            SemanticFragmenter(
                weak_min_chars=weak_min,
                soft_limit_chars=soft_limit,
                hard_limit_chars=hard_limit,
                strong_min_chars=strong_min,
                semantic_wait_seconds=semantic_wait_seconds,
            )
            if semantic_stream
            else TextStreamProcessor()
        )
        full_response = ""
        fenced = False
        history_transaction = None
        history_committed = False

        begin_history = getattr(self, "begin_history_turn", None)
        turn_id = str((datainfo or {}).get("turn_id") or uuid4().hex)
        if callable(begin_history):
            history_transaction = begin_history(message, turn_id=turn_id)
        
        target_avatar = (avatar_stream or self.parent) if stream_to_avatar else None
        fragment_sequence = 0
        on_mode = (datainfo or {}).get("on_mode")
        on_board = (datainfo or {}).get("on_board")
        incremental_board = bool((datainfo or {}).get("incremental_board"))
        incremental_started = False

        def emit_board_item(index: int, item: BoardItem) -> None:
            nonlocal incremental_started
            if not callable(on_board) or fenced:
                return
            if not incremental_started:
                on_board({"kind": "begin", "title": "看板回覆", "turn_id": turn_id})
                incremental_started = True
            on_board({
                "kind": "item",
                "index": index,
                "title": normalize_visible_text(item.title),
                "body": normalize_visible_text(item.content),
                "turn_id": turn_id,
            })

        parser = ResponseProtocolParser(
            mode=norm_mode,
            max_items=max_items,
            on_mode=on_mode if callable(on_mode) else None,
            on_board_item=emit_board_item if incremental_board else None,
        )
        if norm_mode != ReplyMode.AUTO and callable(on_mode):
            on_mode(norm_mode)
        legacy_splitter = AnswerBoardSplitter()
        is_legacy_markup = False
        spoken_response = ""
        def send_to_avatar(text: str) -> None:
            nonlocal fragment_sequence, spoken_response
            if not text:
                return
            spoken_response += text
            if target_avatar:
                fragment_info = dict(datainfo or {})
                fragment_info.pop("on_board", None)
                fragment_info.pop("on_mode", None)
                fragment_info.pop("rules_snapshot", None)
                fragment_info.pop("incremental_board", None)
                if (
                    fragment_info.get("turn_id")
                    and fragment_info.get("generation") is not None
                ):
                    fragment_info["fragment_sequence"] = fragment_sequence
                    logger.info(
                        "Queueing turn-aware LLM fragment sequence=%d",
                        fragment_sequence,
                    )
                else:
                    logger.info("Queueing legacy LLM fragment")
                target_avatar.put_msg_txt(text, fragment_info)
                fragment_sequence += 1

        output_locale = str(getattr(profile, "output_locale", "zh-TW") or "zh-TW")
        enforce_locale = bool(getattr(profile, "enforce_output_locale", True))
        assistant_name = str(getattr(profile, "assistant_name", "") or "")
        forbidden_names = list(getattr(profile, "forbidden_self_names", []) or [])

        def normalize_visible_text(text: str) -> str:
            normalized = normalize_assistant_identity(
                normalize_output_text(text, locale=output_locale, enabled=enforce_locale),
                assistant_name=assistant_name,
                forbidden_names=forbidden_names,
            )
            return strip_unsolicited_self_introduction(
                normalized, user_message=message, assistant_name=assistant_name
            )

        def normalize_board(payload: BoardPayload) -> BoardPayload:
            return BoardPayload(
                title=normalize_visible_text(payload.title),
                summary=normalize_visible_text(payload.summary or "") or None,
                items=[
                    BoardItem(
                        title=normalize_visible_text(item.title),
                        content=normalize_visible_text(item.content),
                        subtitle=normalize_visible_text(item.subtitle or "") or None,
                        badge=normalize_visible_text(item.badge or "") or None,
                    )
                    for item in payload.items
                ],
            )

        def emit_board(payload) -> None:
            if payload is None or not callable(on_board) or fenced:
                return
            if isinstance(payload, BoardPayload):
                payload = normalize_board(payload)
                board_dict = payload.to_dict()
                board_dict["turn_id"] = turn_id
                if incremental_started:
                    board_dict["incremental"] = True
                on_board(board_dict)
                self.queue_board_for_display(SessionBoardContext(
                    turn_id=turn_id,
                    title=payload.title,
                    summary=payload.summary,
                    items=payload.items,
                ))
            else:
                on_board({"kind": "begin", "title": payload.title, "turn_id": turn_id})
                for index, item in enumerate(payload.items):
                    on_board({
                        "kind": "item",
                        "index": index,
                        "title": item.title,
                        "body": getattr(item, "body", getattr(item, "content", "")),
                        "turn_id": turn_id,
                    })
                on_board({"kind": "end", "turn_id": turn_id})
        
        try:
            # 記錄首包延遲，方便定位 LLM 響應瓶頸
            first_chunk = True
            sequence = -1
            if history_transaction is None:
                chunks = self.chat_stream(message, system_prompt=composed_system_prompt)
            else:
                chunks = self.chat_stream(
                    message,
                    system_prompt=composed_system_prompt,
                    history_transaction=history_transaction,
                )
            for sequence, chunk in enumerate(chunks):
                if chunk_guard is not None and not chunk_guard(sequence):
                    fenced = True
                    break
                if first_chunk:
                    first_chunk_time = time.perf_counter()
                    logger.info(f"Time to first chunk: {first_chunk_time - start_time:.3f}s")
                    first_chunk = False
                
                full_response += chunk

                if "<<<BOARD" in chunk or is_legacy_markup:
                    is_legacy_markup = True
                    deltas = legacy_splitter.feed(chunk)
                else:
                    deltas = parser.feed(chunk)

                for spoken in deltas:
                    spoken = normalize_visible_text(spoken)
                    if target_avatar and semantic_stream:
                        notify_chunk = getattr(target_avatar, "notify_llm_chunk", None)
                        if callable(notify_chunk):
                            notify_chunk(
                                spoken,
                                {
                                    **dict(datainfo or {}),
                                    "llm_sequence": sequence,
                                },
                            )
                    if target_avatar:
                        if semantic_stream:
                            for fragment in text_processor.feed(spoken):
                                send_to_avatar(fragment)
                        else:
                            text_processor.process_chunk(spoken, send_to_avatar)
                    else:
                        spoken_response += spoken
            
            if not fenced:
                if is_legacy_markup:
                    leftover, board_payload = legacy_splitter.flush()
                    flush_deltas = [leftover] if leftover else []
                else:
                    flush_deltas, board_payload = parser.flush()

                for delta in flush_deltas:
                    if not delta:
                        continue
                    delta = normalize_visible_text(delta)
                    if target_avatar and semantic_stream:
                        notify_chunk = getattr(target_avatar, "notify_llm_chunk", None)
                        if callable(notify_chunk):
                            notify_chunk(
                                delta,
                                {
                                    **dict(datainfo or {}),
                                    "llm_sequence": max(sequence, 0),
                                },
                            )
                    if target_avatar:
                        if semantic_stream:
                            for fragment in text_processor.feed(delta):
                                send_to_avatar(fragment)
                        else:
                            text_processor.process_chunk(delta, send_to_avatar)
                    else:
                        spoken_response += delta

                if target_avatar:
                    if semantic_stream:
                        for fragment in text_processor.flush():
                            send_to_avatar(fragment)
                    else:
                        text_processor.flush(send_to_avatar)
                emit_board(board_payload)
            
            total_time = time.perf_counter()
            logger.info(f"Total LLM response time: {total_time - start_time:.3f}s")

            clean_spoken = normalize_visible_text(
                spoken_response.strip() or parser.speech_text.strip()
            )
            # The parser is the sole authority for visible content. Never fall
            # back to raw model output after structured data was suppressed.
            clean_full = "" if parser.structured_payload_suppressed else full_response.strip()

            if history_transaction is not None and not defer_history_commit:
                self.commit_history_turn(
                    history_transaction,
                    assistant_text="" if fenced else (clean_spoken or clean_full),
                    terminal_reason="cancelled" if fenced else "completed",
                )
                history_committed = True
            
            return clean_spoken or clean_full
            
        except Exception as e:
            if (
                history_transaction is not None
                and not history_committed
                and not defer_history_commit
            ):
                try:
                    self.commit_history_turn(
                        history_transaction,
                        assistant_text="",
                        terminal_reason="llm_error",
                    )
                except Exception:
                    logger.exception("Failed to commit terminal LLM history transaction")
            logger.error("LLM response generation failed: %s", type(e).__name__)
            raise
