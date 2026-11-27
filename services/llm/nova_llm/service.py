# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""Conversation memory the LLM layer still keeps, keyed by the core's session ids.

One model client per conversation and role holds that role's committed
history and its displayed board. The core decides when a turn is committed,
discarded or forgotten (``src.llm.adapter``).
"""

from __future__ import annotations

from typing import Any, Callable

from src.llm.base import BaseLLM, load_system_prompt
from src.llm.engines import OpenAILLM
from src.utils.logging import logger

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-plus"
LOCAL_API_KEY = "nova-avatar-local"

EngineFactory = Callable[..., BaseLLM]


class LlmSessions:
    """Every conversation's model clients, the role each one is talking to, and its last greeting."""

    def __init__(self, create_engine: EngineFactory = OpenAILLM) -> None:
        self._create_engine = create_engine
        self._instances: dict[Any, BaseLLM] = {}
        self._active_profiles: dict[int, str] = {}
        self._latest_greetings: dict[Any, str] = {}

    def _key(self, sessionid, profile_id=None):
        profile_id = self._active_profiles.get(sessionid, "") if profile_id is None else profile_id
        return (sessionid, profile_id) if profile_id else sessionid

    @staticmethod
    def _owned_by(key, sessionid) -> bool:
        return key == sessionid or isinstance(key, tuple) and key[0] == sessionid

    def select_profile(self, sessionid: int, profile_id: str = "") -> None:
        """Select a stored identity without erasing any role's committed history."""
        if profile_id:
            self._active_profiles[sessionid] = profile_id
        else:
            self._active_profiles.pop(sessionid, None)

    def remember_greeting(self, sessionid, text, *, profile_id="") -> None:
        """Replace one played receipt; never append artificial visitor history."""
        self._latest_greetings[self._key(sessionid, profile_id)] = str(text)

    def _clear_greetings(self, sessionid, profile_id=None) -> None:
        for key in list(self._latest_greetings):
            if self._owned_by(key, sessionid) and (
                    profile_id is None or key == self._key(sessionid, profile_id)):
                self._latest_greetings.pop(key, None)

    def instance(self, sessionid: int, config) -> BaseLLM:
        """The conversation's client for ``config.profile_id``, created on first use."""
        profile_id = getattr(config, "profile_id", "")
        self.select_profile(sessionid, profile_id)
        key = self._key(sessionid)
        if key not in self._instances:
            logger.info(f"Creating new LLM instance for session {sessionid}")
            self._instances[key] = self._create_engine(
                config=config,
                api_key=config.llm.api_key or LOCAL_API_KEY,
                base_url=config.llm.base_url or DEFAULT_BASE_URL,
                model=config.llm.model or DEFAULT_MODEL,
                max_history=10,  # 保留最近10輪對話
            )
        return self._instances[key]

    def prepare_reply(self, sessionid: int, config) -> tuple[BaseLLM, str]:
        """The client for one answer, pointed at ``config``, and the role's last greeting."""
        llm = self.instance(sessionid, config)
        llm.config = config
        llm.system_prompt = load_system_prompt(config)
        llm.base_url = config.llm.base_url or DEFAULT_BASE_URL
        llm.model = config.llm.model or DEFAULT_MODEL
        # The key belongs to the same allowlisted endpoint as base_url;
        # never fall back to another provider's key for a keyless endpoint.
        llm.api_key = config.llm.api_key or LOCAL_API_KEY
        return llm, self._latest_greetings.get(self._key(sessionid), "")

    def begin_turn(self, sessionid: int, config, message: str, turn_id: str) -> None:
        """A fixed handoff announcement commits through the same playback transaction."""
        self.instance(sessionid, config).begin_history_turn(message, turn_id=turn_id)

    def discard_turn(self, sessionid: int, turn_id: str) -> bool:
        """Drop the pending history of an answer that was generated but never played."""
        llm = self._instances.get(self._key(sessionid))
        discard = getattr(llm, "discard_pending_history_turn", None)
        return bool(discard(turn_id)) if callable(discard) else False

    def commit_turn(self, sessionid: int, turn_id: str, *, assistant_text: str,
                    terminal_reason: str) -> bool:
        """Commit exactly what crossed the playback boundary for one voice turn."""
        llm = self._instances.get(self._key(sessionid))
        commit = getattr(llm, "commit_pending_history_turn", None)
        if not callable(commit):
            return False
        return bool(commit(turn_id, assistant_text=assistant_text,
                           terminal_reason=terminal_reason))

    def history(self, sessionid: int, profile_id=None) -> list:
        llm = self._instances.get(self._key(sessionid, profile_id))
        return list(getattr(llm, "conversation_history", [])) if llm else []

    def acknowledge_board_item(self, sessionid: int, *, turn_id: str, board_id: str,
                               item_index: int) -> bool:
        """Commit one board item only after its assigned presenter rendered it."""
        llm = self._instances.get(self._key(sessionid))
        acknowledge = getattr(llm, "acknowledge_board_display", None)
        if not callable(acknowledge):
            return False
        return bool(acknowledge(turn_id=turn_id, board_id=board_id, item_index=item_index))

    def clear(self, sessionid: int, profile_id=None) -> None:
        """清空指定會話的對話歷史與看板快照"""
        self._clear_greetings(sessionid, profile_id)
        keys = [key for key in self._instances
                if self._owned_by(key, sessionid)
                and (profile_id is None or key == self._key(sessionid, profile_id))]
        for key in keys:
            llm = self._instances[key]
            llm.clear_history()
            llm.set_last_board(None)
            logger.info(f"Cleared history and board for session {sessionid}")

    def remove(self, sessionid: int) -> None:
        """刪除指定會話的 LLM 例項"""
        self._clear_greetings(sessionid)
        for key in list(self._instances):
            if self._owned_by(key, sessionid):
                del self._instances[key]
        self._active_profiles.pop(sessionid, None)

    def memory(self, sessionid: int, limit: int = 20, profile_id=None) -> dict:
        llm = self._instances.get(self._key(sessionid, profile_id))
        if llm is None:
            return {"retained_messages": 0, "max_messages": limit,
                    "pending_max_messages": None, "evicted_messages": 0,
                    "oldest_message": None, "oldest_message_number": None, "context": None}
        return {**llm._history.info(), "context": llm.context_usage}

    def set_history_limit(self, sessionid: int, limit: int) -> None:
        for key, llm in list(self._instances.items()):
            if self._owned_by(key, sessionid):
                llm._history.set_limit(limit)

    def has_records(self, sessionid: int) -> bool:
        """Whether any role of the conversation remembers a message or a board."""
        return any(self._owned_by(key, sessionid)
                   and (bool(getattr(llm, "conversation_history", []))
                        or llm.get_last_board() is not None)
                   for key, llm in list(self._instances.items()))

    def switch_endpoint(
        self,
        model: str,
        base_url: str = None,
        extra_body=None,
        api_key: str = None,
        max_tokens: int = None,
        response_max_chars: int = None,
        system_prompt: str = None,
        reset_history: bool = False,
    ) -> None:
        """更新已有會話的模型與介面，base_url 變化時重建客戶端。"""
        for sessionid, llm in self._instances.items():
            if getattr(getattr(llm, "config", None), "conversation_snapshot", False):
                continue
            llm.model = model
            if base_url:
                llm.base_url = base_url
                llm._client = None
            if extra_body is not None:
                llm.extra_body = dict(extra_body)
            if api_key:
                llm.api_key = api_key
                llm._client = None
            if max_tokens is not None:
                llm.max_tokens = int(max_tokens)
            if response_max_chars is not None:
                llm.response_max_chars = int(response_max_chars)
            if system_prompt is not None:
                llm.system_prompt = system_prompt
            if reset_history:
                llm.clear_history()
                llm.set_last_board(None)
            logger.info(
                f"Updated LLM for session {sessionid}: model={llm.model}, base_url={llm.base_url}"
            )
