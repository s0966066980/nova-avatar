# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Transactional conversation history for streamed voice turns."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import RLock


class HistoryTurnState(str, Enum):
    PENDING = "pending"
    COMMITTED = "committed"


@dataclass
class HistoryTransaction:
    turn_id: str
    user_text: str
    state: HistoryTurnState = HistoryTurnState.PENDING
    terminal_reason: str | None = None


class TransactionalHistory:
    """Keep generated output pending until playback chooses what to commit."""

    def __init__(self, *, max_turns: int) -> None:
        if max_turns < 1:
            raise ValueError("max turns must be positive")
        self._max_messages = max_turns * 2
        self._messages: list[dict[str, str]] = []
        self._pending: dict[str, HistoryTransaction] = {}
        self._lock = RLock()

    def begin(self, user_text: str, *, turn_id: str) -> HistoryTransaction:
        if not turn_id:
            raise ValueError("turn id is required")
        with self._lock:
            if turn_id in self._pending:
                raise ValueError(f"history turn already pending: {turn_id}")
            transaction = HistoryTransaction(turn_id=turn_id, user_text=user_text)
            self._pending[turn_id] = transaction
            return transaction

    def request_messages(self, transaction: HistoryTransaction) -> list[dict[str, str]]:
        with self._lock:
            self._require_pending(transaction)
            return [
                *[dict(item) for item in self._messages],
                {"role": "user", "content": transaction.user_text},
            ]

    def preview_messages(self, user_text: str) -> list[dict[str, str]]:
        with self._lock:
            return [
                *[dict(item) for item in self._messages],
                {"role": "user", "content": user_text},
            ]

    def commit(
        self,
        transaction: HistoryTransaction,
        *,
        assistant_text: str,
        terminal_reason: str,
    ) -> None:
        if not terminal_reason:
            raise ValueError("terminal reason is required")
        with self._lock:
            self._require_pending(transaction)
            self._messages.append({"role": "user", "content": transaction.user_text})
            if assistant_text:
                self._messages.append({"role": "assistant", "content": assistant_text})
            self._messages = self._messages[-self._max_messages :]
            transaction.state = HistoryTurnState.COMMITTED
            transaction.terminal_reason = terminal_reason
            del self._pending[transaction.turn_id]

    def commit_pending(
        self,
        turn_id: str,
        *,
        assistant_text: str,
        terminal_reason: str,
    ) -> bool:
        """Atomically commit a pending turn by identity.

        Playback owns this boundary, so duplicate terminal callbacks are a
        harmless no-op instead of a second history append.
        """
        with self._lock:
            transaction = self._pending.get(turn_id)
            if transaction is None:
                return False
            self.commit(
                transaction,
                assistant_text=assistant_text,
                terminal_reason=terminal_reason,
            )
            return True

    def append_message(self, role: str, content: str) -> None:
        with self._lock:
            self._messages.append({"role": role, "content": content})
            self._messages = self._messages[-self._max_messages :]

    def snapshot(self) -> list[dict[str, str]]:
        with self._lock:
            return [dict(item) for item in self._messages]

    def clear(self) -> None:
        with self._lock:
            self._messages.clear()
            self._pending.clear()

    def _require_pending(self, transaction: HistoryTransaction) -> None:
        if (
            transaction.state != HistoryTurnState.PENDING
            or self._pending.get(transaction.turn_id) is not transaction
        ):
            raise RuntimeError(f"history turn is not pending: {transaction.turn_id}")
