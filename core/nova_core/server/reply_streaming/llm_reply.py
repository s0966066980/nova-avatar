# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The core's side of one LLM reply: read its events, review and play its speech.

The LLM service streams ``ReplyEvent``s (ADR 0027). Spoken deltas go to the
core's ``ReplySpeech``, which cuts playable fragments and has each one
reviewed by the service (``review_fragment``); the review state stays here.
The core cancels the reply by closing the stream: when its chunk guard
fences the turn, or when the web-speech bound was reached.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable, Optional

from nova_contracts.llm import (
    BoardItemShown,
    BoardStart,
    FragmentReviewContext,
    FragmentReviewRequest,
    LlmService,
    LlmSession,
    ModelChunk,
    ReplyDone,
    ReplyModeChosen,
    ReplyRequest,
    ReplyStarted,
    ReviewState,
    ReviewedFragment,
    SpeechEnd,
    SpeechSink,
    SpokenDelta,
)
from nova_llm.config_section import llm_session
from nova_core.utils.spoken_text import join_spoken_fragments


def conversation_session(config, published, session_id: int, *, profile: Any = None) -> LlmSession:
    """The LLM session of a conversation configured by ``config``.

    A conversation without its own role profile speaks with the published
    assistant profile unless the turn captured one (``profile``).
    """
    if profile is None:
        owner = config if getattr(config, "profile_id", "") else published
        profile = getattr(getattr(owner, "llm", None), "assistant_profile", None)
    return llm_session(config, session_id, profile=profile)


class ServiceFragmentReview:
    """``FragmentReview`` over the service: one answer's review state, kept by the core.

    ``review`` may be called from the fragmenter's timer thread; calls are
    serialized so the state passes from one fragment to the next.
    """

    def __init__(self, llm: LlmService, started: ReplyStarted) -> None:
        self._llm = llm
        self._context: FragmentReviewContext = started.review
        self._bounded = started.bounded
        self._previews = started.previews_fragments
        self._state = ReviewState()
        self._answer = ""
        self._lock = RLock()

    @property
    def bounded(self) -> bool:
        return self._bounded

    @property
    def previews_fragments(self) -> bool:
        return self._previews

    @property
    def stopped(self) -> bool:
        with self._lock:
            return self._state.stopped

    @property
    def spoken(self) -> str:
        with self._lock:
            return join_spoken_fragments(self._state.accepted)

    @property
    def answer(self) -> str:
        """The cleaned spoken answer the service made of every accepted fragment."""
        with self._lock:
            return self._answer

    def review(self, fragment: str) -> Optional[ReviewedFragment]:
        if not fragment:
            return None
        with self._lock:
            if self._state.stopped:
                return None
            verdict = self._llm.review_fragment(FragmentReviewRequest(
                context=self._context, state=self._state, fragment=fragment))
            self._state = verdict.state
            self._answer = verdict.answer
            return verdict.fragment


@dataclass(frozen=True)
class ReplyOutcome:
    turn_id: str
    # The spoken answer: reviewed speech when any was accepted, else the layer's.
    text: str
    fenced: bool = False


def stream_reply(
    llm: LlmService,
    request: ReplyRequest,
    *,
    speech: Optional[SpeechSink] = None,
    chunk_guard: Optional[Callable[[int], bool]] = None,
    on_mode: Optional[Callable[[str], None]] = None,
    on_board: Optional[Callable[[dict], None]] = None,
) -> ReplyOutcome:
    """Run one reply to its end, or until the core stops reading it. Blocking."""
    events = iter(llm.reply(request))
    review: Optional[ServiceFragmentReview] = None
    done: Optional[ReplyDone] = None
    turn_id = request.turn_id
    fenced = False
    try:
        for event in events:
            if isinstance(event, ReplyStarted):
                turn_id = event.turn_id
                review = ServiceFragmentReview(llm, event)
                if speech is not None:
                    speech.open(review)
            elif isinstance(event, ModelChunk):
                if review is not None and review.stopped:
                    break  # the web bound was reached
                if chunk_guard is not None and not chunk_guard(event.llm_sequence):
                    fenced = True
                    break
            elif isinstance(event, (SpokenDelta, SpeechEnd)):
                if speech is not None:
                    speech.send(event)
                if isinstance(event, SpokenDelta) and review is not None and review.stopped:
                    break  # the web bound was reached; read no further chunk
            elif isinstance(event, ReplyModeChosen):
                if on_mode is not None:
                    on_mode(event.mode)
            elif isinstance(event, ReplyDone):
                done = event
            elif on_board is not None:
                on_board(board_message(event))
    finally:
        close = getattr(events, "close", None)
        if callable(close):
            close()
        if speech is not None:
            speech.close()
    clean = ""
    if speech is not None and review is not None and review.spoken.strip():
        clean = review.answer
    elif done is not None:
        clean = done.spoken
    return ReplyOutcome(turn_id=turn_id, text=clean or (done.visible if done else ""),
                        fenced=fenced)


def board_message(event) -> dict:
    """A board event as the console's board message."""
    if isinstance(event, BoardStart):
        return {"kind": "begin", "title": event.title, "turn_id": event.turn_id}
    if isinstance(event, BoardItemShown):
        return {"kind": "item", "index": event.index, "title": event.title,
                "body": event.body, "turn_id": event.turn_id}
    board = {
        "title": event.title,
        "summary": event.summary,
        "items": [
            {
                "title": item.title,
                "content": item.content,
                "body": item.content,
                **({"subtitle": item.subtitle} if item.subtitle else {}),
                **({"badge": item.badge} if item.badge else {}),
            }
            for item in event.items
        ],
        "turn_id": event.turn_id,
    }
    if event.incremental:
        board["incremental"] = True
    return board
