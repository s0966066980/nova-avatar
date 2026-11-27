# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""An ``LlmService`` for core tests: the in-process service with a scripted ``reply``.

Everything but ``reply`` is the real adapter, so conversation memory, fragment
review and the tools behave as in production; only the model's answer is
scripted. ``requests`` records every ``ReplyRequest`` the core sent.
"""
from __future__ import annotations

from contextlib import contextmanager
from uuid import uuid4
from typing import Callable, Iterable, Iterator, Optional, Union

from nova_contracts.llm import (
    AssistantProfile,
    Board,
    BoardEntry,
    BoardItemShown,
    BoardStart,
    FragmentReviewContext,
    ModelChunk,
    ReplyDone,
    ReplyEvent,
    ReplyModeChosen,
    ReplyRequest,
    ReplyStarted,
    SpeechEnd,
    SpokenDelta,
)
from nova_contracts.llm import LlmEngineSettings, LocalServer, LocalServerSettings, Question, TurnCommit
from src.llm.adapter import InProcessLlmService
from src.llm.config_section import reply_rules
from src.server.reply_streaming.llm_reply import conversation_session, stream_reply

Script = Callable[[ReplyRequest], Union[str, Iterable[ReplyEvent]]]


def started(request: ReplyRequest, **fields) -> ReplyStarted:
    """The first event of a reply to ``request``."""
    return ReplyStarted(turn_id=request.turn_id or "turn",
                        review=FragmentReviewContext(profile=AssistantProfile()), **fields)


def reply_events(request: ReplyRequest, text: str, *, speak: bool = True,
                 mode: Optional[str] = None) -> Iterator[ReplyEvent]:
    """The events of a one-chunk answer saying ``text``.

    With ``speak`` the text streams as a spoken delta the core plays; without
    it only ``ReplyDone`` carries the answer, as for a reply nobody listens to.
    """
    yield started(request)
    if mode is not None:
        yield ReplyModeChosen(mode=mode)
    yield ModelChunk(llm_sequence=0)
    if speak and text:
        yield SpokenDelta(text=text, llm_sequence=0)
        yield SpeechEnd()
    yield ReplyDone(spoken=text, visible=text)


def board_events(request: ReplyRequest, title: str, items: list[tuple[str, str]], *,
                 incremental: bool = False) -> Iterator[ReplyEvent]:
    """Board events for ``items`` of ``(title, content)``, shown one by one or as a whole."""
    turn_id = request.turn_id or "turn"
    if incremental:
        yield BoardStart(turn_id=turn_id, title=title)
        for index, (item_title, content) in enumerate(items):
            yield BoardItemShown(turn_id=turn_id, index=index, title=item_title, body=content)
    yield Board(turn_id=turn_id, title=title, incremental=incremental,
                items=tuple(BoardEntry(title=t, content=c) for t, c in items))


class FakeLlm(InProcessLlmService):
    """The in-process service whose answers come from ``script``.

    ``script`` is the answer's text, or a function of the request returning
    the text or the reply events. Text is streamed as a spoken delta unless
    ``speak`` is false.
    """

    def __init__(self, script: Union[str, Script] = "", *, speak: bool = True, **kwargs) -> None:
        super().__init__(**kwargs)
        self.requests: list[ReplyRequest] = []
        self.script = script
        self.speak = speak
        # What the console asked of the service: model switches and owned servers.
        self.engine_settings: list[LlmEngineSettings] = []
        self.local_servers: list[LocalServerSettings] = []

    @property
    def engines(self) -> dict:
        """The model client of every conversation and role, keyed as the service keys them."""
        return self._sessions._instances

    @property
    def calls(self) -> int:
        return len(self.requests)

    @property
    def request(self) -> ReplyRequest:
        """The only request sent."""
        assert len(self.requests) == 1, f"{len(self.requests)} replies requested"
        return self.requests[0]

    def apply_engine(self, settings: LlmEngineSettings) -> LlmEngineSettings:
        self.engine_settings.append(settings)
        return super().apply_engine(settings)

    def start_local_server(self, settings: LocalServerSettings) -> LocalServer:
        """Never starts a process: reports the server the settings describe."""
        self.local_servers.append(settings)
        return LocalServer(base_url=f"http://{settings.host}:{settings.port}/v1")

    def assert_not_called(self) -> None:
        assert not self.requests, f"{len(self.requests)} replies requested"

    def assert_called_once(self) -> None:
        assert len(self.requests) == 1, f"{len(self.requests)} replies requested"

    def reply(self, request: ReplyRequest) -> Iterator[ReplyEvent]:
        self.requests.append(request)
        script = self.script(request) if callable(self.script) else self.script
        if isinstance(script, str):
            yield from reply_events(request, script, speak=self.speak)
        else:
            yield from script


@contextmanager
def answering(voice, script: Union[str, Script] = "", *, speak: bool = False):
    """Script the answers ``voice`` gets inside the block; yields the service.

    Text is only returned by default (``speak`` false), as when nothing is
    played; the requests recorded start empty and
    stay readable after the block.
    """
    if not isinstance(voice._llm, FakeLlm):
        voice._llm = FakeLlm()
    llm = voice._llm
    saved = llm.script, llm.speak
    llm.script, llm.speak, llm.requests = script, speak, []
    try:
        yield llm
    finally:
        # The requests stay readable after the block.
        llm.script, llm.speak = saved


def ask(llm, avatar, text, *, published=None, speech=None, commit=True):
    """Answer ``text`` for the conversation ``avatar`` belongs to, as the core's routes do.

    ``avatar.config`` is the conversation's configuration (else ``published``);
    the per-turn ``_assistant_profile_snapshot`` and ``_reply_rules_snapshot``
    of ``avatar`` win over the published ones. The answer is committed to the
    conversation's history unless ``commit`` is false. Returns the spoken answer.
    """
    turn_id = uuid4().hex
    config = getattr(avatar, "config", None) or published
    owner = config if getattr(config, "conversation_snapshot", False) else published or config
    session_id = getattr(avatar, "sessionid", 0)
    rules = getattr(avatar, "_reply_rules_snapshot", None) or reply_rules(
        config if getattr(config, "profile_id", "") else owner)
    request = ReplyRequest(
        session=conversation_session(config, owner, session_id,
                                     profile=getattr(avatar, "_assistant_profile_snapshot", None)),
        question=Question(text=text), rules=rules, turn_id=turn_id,
        stream_speech=speech is not None)
    answer = stream_reply(llm, request, speech=speech).text
    if commit:
        llm.commit_turn(TurnCommit(session_id=session_id, turn_id=turn_id, assistant_text=answer,
                                   terminal_reason="completed"))
    return answer
