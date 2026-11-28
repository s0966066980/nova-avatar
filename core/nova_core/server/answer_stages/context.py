# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""What an answer stage sees of a turn, and what a stage hands back.

A stage works on one turn of one conversation. ``StageContext`` is the small surface
it may use (the LLM service, the role's configuration, events to the console, stage
timing and the check that the turn is still current), so a stage never reaches into
``VoiceTurnSession`` and can be written, tested or removed on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional

if TYPE_CHECKING:
    from nova_core.server.voice_session import VoiceTurnSession


@dataclass(frozen=True)
class AnswerInputs:
    """What the main answer is generated from: the question and what stages added to it."""

    text: str
    rag_result: Optional[dict]
    web_result: Optional[dict] = None
    web_selection: Optional[dict] = None
    # A verified quote that answers the question by itself.
    web_quote: Optional[str] = None


@dataclass(frozen=True)
class Speak:
    """A stage's outcome: say this fixed text instead of generating an answer."""

    text: str


class StageContext:
    """One turn's view of the session for the stages that prepare its answer."""

    def __init__(self, session: "VoiceTurnSession", turn_id: str, generation: int, *,
                 retrieval_budget: float = 0.3) -> None:
        self._session = session
        self.turn_id = turn_id
        self.generation = generation
        self.retrieval_budget = retrieval_budget

    @property
    def llm(self) -> Any:
        return self._session._llm

    @property
    def config(self) -> Any:
        return self._session.config

    @property
    def avatar_config(self) -> Any:
        """The renderer's configuration when it has one (it carries the role's own media)."""
        avatar = self._session.avatar
        return avatar.config if getattr(avatar, "config", None) else self._session.config

    @property
    def attachments(self) -> Any:
        return self._session.attachments

    @property
    def rag_selection(self) -> dict:
        return self._session._rag_snapshot

    @property
    def web_cache(self) -> Any:
        return self._session._web_cache

    @property
    def locale(self) -> str:
        return self._session._conversation["locale"]

    def is_current(self) -> bool:
        return self._session._is_current(self.turn_id, self.generation)

    def emit(self, event_type: str, **payload: Any) -> None:
        self._session._emit(event_type, turn_id=self.turn_id, **payload)

    def stage_start(self, stage: str) -> None:
        self._session.mark_stage_start(stage)

    def stage_end(self, stage: str) -> None:
        self._session.mark_stage_end(stage)


# A stage of the first phase (before routing, so it can run beside it) takes the inputs
# so far and returns them extended, or ``None`` once the turn is no longer current.
InputStage = Callable[[StageContext, AnswerInputs], Awaitable[Optional[AnswerInputs]]]

# A stage of the second phase (after routing chose the role) additionally receives the
# visitor's own question and the role plan. It returns the inputs to carry on with,
# ``Speak`` to answer with a fixed text, or ``None`` once the turn is no longer current.
AnswerStage = Callable[
    [StageContext, AnswerInputs, str, Optional[dict]], Awaitable["AnswerInputs | Speak | None"]
]
