# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The LLM layer: spoken-text deltas and structured events, handoff decisions, greetings.

The layer produces *spoken text deltas*; the core cuts them into playable
fragments. Transport when split: server-sent events for a reply, JSON for the
rest.
"""
from __future__ import annotations

from typing import Annotated, Any, Iterator, Literal, Protocol

from pydantic import BaseModel, Field


# ---- reply stream events ---------------------------------------------------
class SpokenTextDelta(BaseModel):
    type: Literal["spoken_text"] = "spoken_text"
    text: str


class ReplyModeEvent(BaseModel):
    type: Literal["reply_mode"] = "reply_mode"
    mode: str


class BoardEvent(BaseModel):
    type: Literal["board"] = "board"
    payload: dict[str, Any]


class RetrievalSourcesEvent(BaseModel):
    type: Literal["retrieval_sources"] = "retrieval_sources"
    sources: list[dict[str, Any]]


class WebSourcesEvent(BaseModel):
    type: Literal["web_sources"] = "web_sources"
    sources: list[dict[str, Any]]


class ReplyDone(BaseModel):
    type: Literal["done"] = "done"
    text: str


LlmEvent = Annotated[
    SpokenTextDelta | ReplyModeEvent | BoardEvent | RetrievalSourcesEvent | WebSourcesEvent | ReplyDone,
    Field(discriminator="type"),
]


class ReplyRequest(BaseModel):
    message: str
    turn_id: str
    generation: int
    reply_mode: str | None = None
    rag_context: str = ""


# ---- handoff decision ------------------------------------------------------
class WeatherSite(BaseModel):
    county: str = ""
    town: str = ""


class HandoffMember(BaseModel):
    id: str
    name: str
    main: bool = False
    description: str = ""
    rules: str = ""
    weather: WeatherSite | None = None  # set only on the weather-tool holder


class HandoffRequest(BaseModel):
    members: list[HandoffMember]
    current_id: str
    text: str
    history: list[dict[str, Any]] = []
    confirmed: dict[str, Any] = {}
    explain: bool = False


class HandoffDecision(BaseModel):
    target: str | None  # None: ask the visitor to clarify
    clarification: str = ""
    context: str = ""
    county: str = ""
    town: str = ""
    kind: str = ""
    start_date: str = ""
    end_date: str = ""
    accepted_at: str = ""
    decided_by: str = ""
    reason: str = ""


# ---- idle greeting ---------------------------------------------------------
class GreetingRequest(BaseModel):
    prompt: str
    min_chars: int
    max_chars: int


class GreetingResult(BaseModel):
    text: str


class LlmService(Protocol):
    def route(self, request: HandoffRequest) -> HandoffDecision: ...

    async def generate_greeting(self, request: GreetingRequest) -> GreetingResult: ...

    def stream_reply(self, request: ReplyRequest) -> Iterator[LlmEvent]:
        """Yield events for one reply; closing the iterator cancels it."""
