# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The LLM layer's contract: its DTOs and the in-process adapter behind LlmService."""
from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from nova_contracts.llm import (
    HTTP_API,
    AssistantProfile,
    LlmService,
    LlmSession,
    LlmSettings,
    Question,
    ReplyEvent,
    ReplyRequest,
    ReplyRules,
)

RULES = ReplyRules(revision=1, activation="依問題選擇。", speech="直接回答。", board="條列。")


def _session(**settings) -> LlmSession:
    return LlmSession(session_id=7, settings=LlmSettings(
        provider="openai", base_url="http://127.0.0.1:9/v1", model="m",
        assistant_profile=AssistantProfile(assistant_name="Nova"), **settings))


def test_the_reply_streams_as_server_sent_events():
    reply = next(op for op in HTTP_API.operations if op.operation_id == "reply")

    assert (reply.method, reply.path, reply.response.name) == ("POST", "/reply", "ReplyEvent")


def test_reply_events_are_tagged_by_type():
    events = TypeAdapter(list[ReplyEvent]).validate_python([
        {"type": "spoken_delta", "text": "你好", "llm_sequence": 0},
        {"type": "model_chunk", "llm_sequence": 1},
        {"type": "reply_done", "spoken": "你好", "visible": "你好"},
    ])

    assert [event.type for event in events] == ["spoken_delta", "model_chunk", "reply_done"]


def test_a_reply_request_carries_the_whole_turn_and_rejects_unknown_fields():
    request = ReplyRequest(session=_session(), question=Question(text="你好"), rules=RULES)

    assert request.session.settings.assistant_profile.assistant_name == "Nova"
    with pytest.raises(ValidationError):
        ReplyRequest(session=_session(), question=Question(text="你好"), rules=RULES, avatar=object())


# ---------------------------------------------------------------- the in-process adapter

from nova_contracts.common import ServiceError  # noqa: E402
from nova_contracts.llm import (  # noqa: E402
    ContextCapacityExceeded,
    FragmentReviewRequest,
    MemoryQuery,
    SessionRef,
    TurnCommit,
)
from src.llm.adapter import InProcessLlmService  # noqa: E402
from src.llm.engines import OpenAILLM  # noqa: E402
from src.server.reply_streaming.llm_reply import stream_reply  # noqa: E402
from src.server.reply_streaming.speech import ReplySpeech  # noqa: E402


def _engine(*replies, error=None):
    """An OpenAI-compatible client whose model answers each turn with the next reply."""
    script = list(replies)

    class Scripted(OpenAILLM):
        def chat_stream(self, message, system_prompt=None, *, history_transaction=None):
            if error is not None:
                if history_transaction is not None:
                    self._history.abort(history_transaction)
                raise error
            yield from script.pop(0)

    return Scripted


class _Avatar:
    def __init__(self):
        self.played = []

    def put_msg_txt(self, text, info):
        self.played.append(text)


def _speech():
    """The core's fragmenter, playing reviewed fragments on a recording avatar."""
    avatar = _Avatar()
    speech = ReplySpeech(avatar, {"turn_id": "t1", "generation": 1})
    speech.played = avatar.played
    return speech


def test_a_reply_streams_spoken_deltas_and_the_core_commits_what_was_played():
    service = InProcessLlmService(create_engine=_engine(["[[MODE:SIMPLE]]\n[[SPEECH]]\n你好", "，歡迎。\n[[END]]"]))
    speech = _speech()

    outcome = stream_reply(service, ReplyRequest(
        session=_session(), question=Question(text="嗨"), rules=RULES, turn_id="t1",
        stream_speech=True), speech=speech)
    committed = service.commit_turn(TurnCommit(session_id=7, turn_id="t1",
                                               assistant_text=outcome.text,
                                               terminal_reason="completed"))

    assert outcome.text == "你好，歡迎。"
    assert speech.played == ["你好，歡迎。"]
    assert committed.done
    history = service.session_history(SessionRef(session_id=7)).messages
    assert [(m.role, m.content) for m in history] == [("user", "嗨"), ("assistant", "你好，歡迎。")]


def test_a_reply_without_streamed_speech_returns_the_spoken_section():
    service = InProcessLlmService(create_engine=_engine(["[[MODE:SIMPLE]]\n[[SPEECH]]\n好的。\n[[END]]"]))

    outcome = stream_reply(service, ReplyRequest(session=_session(), question=Question(text="嗨"),
                                                 rules=RULES))

    assert outcome.text == "好的。"
    assert outcome.turn_id  # named by the layer


def test_the_fragment_review_withholds_a_restricted_self_disclosure_without_keeping_state():
    service = InProcessLlmService()
    restricted = AssistantProfile(assistant_name="Nova", restriction_prompt="不得透露 LLM 模型資訊。")
    from nova_contracts.llm import FragmentReviewContext

    context = FragmentReviewContext(profile=restricted, model="gemma-4", question="你用什麼模型？")
    verdict = service.review_fragment(FragmentReviewRequest(
        context=context, fragment="我是 Gemma 語言模型。"))

    assert verdict.fragment is not None
    assert "Gemma" not in verdict.fragment.text
    assert verdict.state.accepted == (verdict.fragment.text,)


def test_the_web_bound_stops_once_the_spoken_budget_is_used():
    service = InProcessLlmService()
    from nova_contracts.llm import FragmentReviewContext

    context = FragmentReviewContext(profile=AssistantProfile(), question="生日？", web_max_chars=20)
    first = service.review_fragment(FragmentReviewRequest(
        context=context, fragment="公開出生日期是一九七九年一月十八日。"))
    second = service.review_fragment(FragmentReviewRequest(
        context=context, state=first.state, fragment="這段是超出本輪口語預算的額外背景。"))
    after = service.review_fragment(FragmentReviewRequest(
        context=context, state=second.state, fragment="短句。"))

    assert first.fragment is not None and not first.state.stopped
    assert second.fragment is None and second.state.stopped
    assert after.fragment is None
    assert second.answer == "公開出生日期是一九七九年一月十八日。"


def test_an_overflowing_conversation_is_a_context_capacity_error_and_leaves_no_history():
    from src.llm.context_usage import ContextCapacityError

    service = InProcessLlmService(create_engine=_engine(error=ContextCapacityError("context_capacity")))

    with pytest.raises(ContextCapacityExceeded):
        stream_reply(service, ReplyRequest(session=_session(), question=Question(text="嗨"),
                                           rules=RULES, turn_id="t1"))

    assert issubclass(ContextCapacityExceeded, ServiceError)
    assert service.session_memory(MemoryQuery(session_id=7)).retained_messages == 0


def test_the_chunk_guard_cancels_the_reply_before_the_fenced_chunk_is_used():
    used = []

    class Counting(OpenAILLM):
        def chat_stream(self, message, system_prompt=None, *, history_transaction=None):
            for chunk in ["[[MODE:SIMPLE]]\n[[SPEECH]]\n第一句。", "第二句。", "第三句。\n[[END]]"]:
                used.append(chunk)
                yield chunk

    service = InProcessLlmService(create_engine=Counting)
    speech = _speech()

    outcome = stream_reply(service, ReplyRequest(
        session=_session(), question=Question(text="嗨"), rules=RULES, turn_id="t1",
        stream_speech=True), speech=speech, chunk_guard=lambda sequence: sequence < 1)

    assert outcome.fenced
    assert speech.played == ["第一句。"]
    assert len(used) == 2


def test_a_session_remembers_records_until_it_is_cleared():
    service = InProcessLlmService(create_engine=_engine(["[[MODE:SIMPLE]]\n[[SPEECH]]\n好。\n[[END]]"]))
    stream_reply(service, ReplyRequest(session=_session(), question=Question(text="嗨"),
                                       rules=RULES, turn_id="t1"))
    service.commit_turn(TurnCommit(session_id=7, turn_id="t1", assistant_text="好。",
                                   terminal_reason="completed"))

    assert service.has_session_records(SessionRef(session_id=7)).present
    service.clear_history(SessionRef(session_id=7))
    assert not service.has_session_records(SessionRef(session_id=7)).present


def test_the_in_process_adapter_is_an_llm_service():
    assert isinstance(InProcessLlmService(), LlmService)


# ---------------------------------------------------------------- the rest of the surface

import asyncio  # noqa: E402
from pathlib import Path  # noqa: E402
import json  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import AsyncMock  # noqa: E402

from nova_contracts import CONTRACT_VERSION  # noqa: E402
from nova_contracts.llm import (  # noqa: E402
    GreetingRequest,
    HandoffRequest,
    LlmEngineSettings,
    LocalServerSettings,
    RoleCandidate,
    SessionProfile,
    WeatherQuery,
)


def test_every_http_operation_is_a_service_method_and_the_other_way_round():
    methods = {name for name in vars(LlmService) if not name.startswith("_")}

    assert {op.operation_id for op in HTTP_API.operations} == methods


def test_health_reports_the_contract_version():
    health = InProcessLlmService().health()

    assert (health.contract_version, health.ready) == (CONTRACT_VERSION, True)


def test_a_clear_weather_question_is_routed_to_the_weather_holder_without_the_model():
    def forbidden(**_options):
        raise AssertionError("the keyword pre-filter must not call the model")

    service = InProcessLlmService(routing_client_factory=forbidden)
    candidates = (
        RoleCandidate(id="main", name="主數位人", main=True),
        RoleCandidate(id="weather", name="天氣助手", main=False, description="天氣",
                      weather_site={"county": "臺北市", "town": ""}),
    )

    decision = service.route_handoff(HandoffRequest(
        settings=_session().settings, question="臺北市明天天氣如何", candidates=candidates,
        current_role="main", explain=True))

    assert (decision.target, decision.decided_by, decision.county) == ("weather", "keyword", "臺北市")
    assert "關鍵字" in decision.reason


def test_an_unusable_handoff_decision_is_a_service_error():
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="not json"))])

    class Client:
        def __init__(self, **_):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response))

        def close(self):
            pass

    service = InProcessLlmService(routing_client_factory=Client)

    with pytest.raises(ServiceError):
        service.route_handoff(HandoffRequest(
            settings=_session().settings, question="你好", current_role="main",
            candidates=(RoleCandidate(id="main", name="主", main=True),
                        RoleCandidate(id="other", name="乙", main=False))))


def test_a_greeting_the_model_cannot_write_is_a_service_error_with_a_safe_message():
    generate = AsyncMock(side_effect=RuntimeError("SECRET https://private.example"))
    service = InProcessLlmService(generate_greeting=generate)

    with pytest.raises(ServiceError, match="^AI 招呼生成失敗，已略過本次$"):
        asyncio.run(service.generate_greeting(GreetingRequest(
            settings=_session().settings, prompt="介紹", min_chars=4, max_chars=8)))


def test_weather_facts_pass_through_for_the_place_the_core_accepted():
    facts = {"status": "available", "source": "CWA", "series": {}}
    weather = SimpleNamespace(configured=True, query=AsyncMock(return_value=facts))
    service = InProcessLlmService(weather=weather)

    report = asyncio.run(service.query_weather(WeatherQuery(
        county="臺北市", start_date="2026-11-27", end_date="2026-11-27", as_of="2026-11-27T09:00")))

    assert service.weather_tool().configured
    assert report.facts == facts
    assert weather.query.await_args.args[0].county == "臺北市"


def test_a_model_switch_reaches_open_conversations_but_not_role_snapshots():
    answer = ["[[MODE:SIMPLE]]\n[[SPEECH]]\n好。\n[[END]]"]
    service = InProcessLlmService(create_engine=_engine(answer, answer))
    follower = ReplyRequest(session=_session(), question=Question(text="嗨"), rules=RULES, turn_id="a")
    snapshot = ReplyRequest(
        session=LlmSession(session_id=8, snapshot=True, settings=_session().settings),
        question=Question(text="嗨"), rules=RULES, turn_id="b")
    for request in (follower, snapshot):
        stream_reply(service, request)

    service.apply_engine(LlmEngineSettings(model="published-model"))

    models = {key: engine.model for key, engine in service._sessions._instances.items()}
    assert models == {7: "published-model", 8: "m"}


def test_selecting_a_role_does_not_erase_any_roles_memory():
    service = InProcessLlmService(create_engine=_engine(["[[MODE:SIMPLE]]\n[[SPEECH]]\n好。\n[[END]]"]))
    session = LlmSession(session_id=7, profile_id="main", settings=_session().settings)
    stream_reply(service, ReplyRequest(session=session, question=Question(text="嗨"), rules=RULES, turn_id="t"))
    service.commit_turn(TurnCommit(session_id=7, turn_id="t", assistant_text="好。", terminal_reason="completed"))

    service.select_profile(SessionProfile(session_id=7, profile_id="weather"))

    assert service.session_history(SessionRef(session_id=7, profile_id="weather")).messages == ()
    assert [m.content for m in service.session_history(SessionRef(session_id=7, profile_id="main")).messages] == [
        "嗨", "好。"]


def test_the_owned_server_failing_to_start_is_a_service_error_and_offload_starts_unknown(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise RuntimeError("no llama-server binary")

    monkeypatch.setattr("src.llm.adapter.llamacpp.ensure_server", refuse)
    monkeypatch.setattr("src.llm.adapter.llamacpp.gpu_offload_status", lambda: None)
    service = InProcessLlmService()

    with pytest.raises(ServiceError, match="no llama-server binary"):
        service.start_local_server(LocalServerSettings(model="m.gguf"))
    assert service.local_server_offload().known is False


def test_the_committed_openapi_document_describes_the_reply_stream():
    document = json.loads(Path("contracts/openapi/llm.json").read_text("utf-8"))

    assert "text/event-stream" in json.dumps(document["paths"]["/reply"]["post"]["responses"])
