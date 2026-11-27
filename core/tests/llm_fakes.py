# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""An ``LlmService`` for core tests: the in-process service with a scripted ``reply``.

Everything but ``reply`` is the real adapter, so conversation memory, fragment
review and the tools behave as in production; only the model's answer is
scripted, and a text answer is produced by the layer's ``fake`` engine. ``requests`` records every ``ReplyRequest`` the core sent.
"""
from __future__ import annotations

from contextlib import contextmanager
from uuid import uuid4
from typing import Callable, Iterable, Iterator, Union

from nova_contracts.llm import (
    AssistantProfile,
    FragmentReviewContext,
    ReplyEvent,
    ReplyRequest,
    ReplyStarted,
)
from nova_contracts.llm import LlmEngineSettings, LocalServer, LocalServerSettings, Question, TurnCommit
from nova_llm.adapter import InProcessLlmService
from nova_llm.engines import FakeLLM
from nova_llm.engines.fake import answer_chunks
from nova_llm.config_section import reply_rules
from nova_core.server.reply_streaming.llm_reply import conversation_session, stream_reply

Script = Callable[[ReplyRequest], Union[str, Iterable[ReplyEvent]]]


def started(request: ReplyRequest, **fields) -> ReplyStarted:
    """The first event of a reply to ``request``."""
    return ReplyStarted(turn_id=request.turn_id or "turn",
                        review=FragmentReviewContext(profile=AssistantProfile()), **fields)


def reply_events(request: ReplyRequest, text: str, *, speak: bool = True) -> Iterator[ReplyEvent]:
    """The events of an answer saying ``text``, produced by the layer's ``fake`` engine.

    With ``speak`` the text streams as spoken deltas the core plays; without
    it only ``ReplyDone`` carries the answer, as for a reply nobody listens to.
    The mode and board reports the request asks for are left out.
    """
    service = InProcessLlmService(
        create_engine=lambda **options: FakeLLM(chunks=answer_chunks(text), **options))
    settings = request.session.settings.model_copy(update={"engine": "fake"})
    return service.reply(request.model_copy(update={
        "session": request.session.model_copy(update={"settings": settings}),
        "turn_id": request.turn_id or "turn", "stream_speech": speak, "reply_mode": "simple",
        "report_mode": False, "report_board": False, "incremental_board": False}))


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
