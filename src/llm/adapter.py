# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""In-process adapter that presents the LLM layer as the ``LlmService`` contract.

The core calls this instead of the layer's modules, so the same calls can later
go over loopback HTTP without the core changing.
"""
from __future__ import annotations

import queue
import threading
from typing import Iterator

from nova_contracts.llm import (
    BoardEvent,
    GreetingRequest,
    GreetingResult,
    HandoffDecision,
    HandoffRequest,
    LlmEvent,
    ReplyDone,
    ReplyModeEvent,
    ReplyRequest,
    SpokenTextDelta,
)
from openai import OpenAI

from src.llm import handoff
from src.llm.base import BaseLLM
from src.llm.greeting import generate_greeting
from src.llm.rules import snapshot_from_config

_END = object()


class _CapturingTarget:
    """Receives the finished spoken fragments of one reply and queues them as events."""

    def __init__(self, events: "queue.Queue", config) -> None:
        self._events = events
        self.config = config
        self.sessionid = 0

    def put_msg_txt(self, msg: str, datainfo: dict | None = None) -> None:
        self._events.put(SpokenTextDelta(text=msg))


class LlmAdapter:
    def __init__(self, config, llm: BaseLLM | None = None, *, clients=None, client_factory=OpenAI) -> None:
        self._config = config
        self._llm = llm
        self._clients = clients
        self._client_factory = client_factory

    def route(self, request: HandoffRequest) -> HandoffDecision:
        members = [member.model_dump() for member in request.members]
        result = handoff.route(
            self._config, members, request.current_id, request.text, list(request.history),
            dict(request.confirmed), clients=self._clients, client_factory=self._client_factory,
            explain=request.explain,
        )
        return HandoffDecision(**result)

    async def generate_greeting(self, request: GreetingRequest) -> GreetingResult:
        text = await generate_greeting(self._config, request.model_dump())
        return GreetingResult(text=text)

    def stream_reply(self, request: ReplyRequest) -> Iterator[LlmEvent]:
        """Yield the reply's events; closing the iterator stops generating."""
        if self._llm is None:
            raise RuntimeError("this adapter was built without a model for replies")
        events: "queue.Queue" = queue.Queue()
        closed = threading.Event()
        target = _CapturingTarget(events, self._config)
        datainfo = {
            "turn_id": request.turn_id,
            "generation": request.generation,
            "rules_snapshot": snapshot_from_config(self._config),
            "on_mode": lambda mode: events.put(ReplyModeEvent(mode=str(getattr(mode, "value", mode)))),
            "on_board": lambda payload: events.put(BoardEvent(payload=dict(payload))),
        }

        def run() -> None:
            try:
                text = self._llm.generate_response(  # type: ignore[union-attr]
                    request.message, target, datainfo=datainfo,
                    chunk_guard=lambda _sequence: not closed.is_set(),
                    reply_mode=request.reply_mode, rag_context=request.rag_context,
                )
                events.put(ReplyDone(text=text))
            except Exception as exc:  # surfaced to the consumer on its own thread
                events.put(exc)
            finally:
                events.put(_END)

        threading.Thread(target=run, daemon=True).start()
        try:
            while True:
                item = events.get()
                if item is _END:
                    return
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            closed.set()
