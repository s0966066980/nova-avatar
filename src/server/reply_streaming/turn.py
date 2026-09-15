# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Turn identity, lifecycle, cancellation, and generation fencing."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import Event, RLock


class TurnState(str, Enum):
    CREATED = "created"
    LLM_STREAMING = "llm_streaming"
    SYNTHESIZING = "synthesizing"
    SPEAKING = "speaking"
    DRAINING = "draining"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


TERMINAL_STATES = frozenset(
    {TurnState.COMPLETED, TurnState.CANCELLED, TurnState.FAILED}
)

_ALLOWED_TRANSITIONS = {
    TurnState.CREATED: {
        TurnState.LLM_STREAMING,
        TurnState.CANCELLED,
        TurnState.FAILED,
    },
    TurnState.LLM_STREAMING: {
        TurnState.SYNTHESIZING,
        TurnState.CANCELLED,
        TurnState.FAILED,
    },
    TurnState.SYNTHESIZING: {
        TurnState.SPEAKING,
        TurnState.CANCELLED,
        TurnState.FAILED,
    },
    TurnState.SPEAKING: {
        TurnState.DRAINING,
        TurnState.CANCELLED,
        TurnState.FAILED,
    },
    TurnState.DRAINING: {
        TurnState.COMPLETED,
        TurnState.CANCELLED,
        TurnState.FAILED,
    },
}


@dataclass(frozen=True)
class TurnEnvelope:
    turn_id: str
    generation: int
    stage: str
    sequence: int


class TurnContext:
    """Thread-safe authority for whether work still belongs to the active turn."""

    def __init__(self, *, turn_id: str, generation: int) -> None:
        if not turn_id:
            raise ValueError("turn id is required")
        if generation < 0:
            raise ValueError("generation cannot be negative")
        self.turn_id = turn_id
        self.generation = generation
        self.cancelled = Event()
        self._state = TurnState.CREATED
        self._terminal_reason: str | None = None
        self._lock = RLock()

    @property
    def state(self) -> TurnState:
        with self._lock:
            return self._state

    @property
    def terminal_reason(self) -> str | None:
        with self._lock:
            return self._terminal_reason

    @property
    def terminal(self) -> bool:
        with self._lock:
            return self._state in TERMINAL_STATES

    def envelope(self, *, stage: str, sequence: int) -> TurnEnvelope:
        if not stage:
            raise ValueError("stage is required")
        if sequence < 0:
            raise ValueError("sequence cannot be negative")
        return TurnEnvelope(
            turn_id=self.turn_id,
            generation=self.generation,
            stage=stage,
            sequence=sequence,
        )

    def accepts(self, envelope: TurnEnvelope) -> bool:
        with self._lock:
            return (
                self._state not in TERMINAL_STATES
                and not self.cancelled.is_set()
                and envelope.turn_id == self.turn_id
                and envelope.generation == self.generation
            )

    def transition(self, next_state: TurnState) -> None:
        next_state = TurnState(next_state)
        with self._lock:
            allowed = _ALLOWED_TRANSITIONS.get(self._state, set())
            if next_state not in allowed:
                raise RuntimeError(
                    f"invalid turn transition: {self._state.value} -> {next_state.value}"
                )
            self._state = next_state

    def cancel(self, reason: str) -> None:
        self._finish(TurnState.CANCELLED, reason)

    def fail(self, reason: str) -> None:
        self._finish(TurnState.FAILED, reason)

    def complete(self, reason: str = "completed") -> None:
        self._finish(TurnState.COMPLETED, reason)

    def _finish(self, state: TurnState, reason: str) -> None:
        if not reason:
            raise ValueError("terminal reason is required")
        with self._lock:
            if self._state in TERMINAL_STATES:
                return
            if state not in _ALLOWED_TRANSITIONS.get(self._state, set()):
                raise RuntimeError(
                    f"invalid turn transition: {self._state.value} -> {state.value}"
                )
            self._terminal_reason = reason
            self._state = state
            if state in {TurnState.CANCELLED, TurnState.FAILED}:
                self.cancelled.set()
