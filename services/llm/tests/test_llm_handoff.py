# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The LLM layer's handoff entry: the core hands it members and context, never the role library."""
from __future__ import annotations

from datetime import datetime
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.llm.handoff import HandoffContext, RoleCandidate, RoutingError, route

TAIPEI_TODAY = datetime.now().date().isoformat()


def _config(locale="zh-TW"):
    return SimpleNamespace(
        llm=SimpleNamespace(provider="llamacpp", model="gemma-4-E2B_q4_0-it", api_key="",
                            base_url="http://127.0.0.1:18080/v1", extra_body={}),
        conversation=SimpleNamespace(locale=locale))


def _client(raw):
    create = Mock(return_value=SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=raw))]))

    class Client:
        def __init__(self, **_):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

        def close(self):
            pass

    return Client, create


MAIN = RoleCandidate(id="main", name="主數位人", main=True,
                     description="公司簡介與一般問題。", rules="")
SERVICE = RoleCandidate(id="service", name="客服小幫手", main=False,
                        description="回答會員、訂單與退換貨問題。", rules="會員或訂單問題交給客服。")
WEATHER = RoleCandidate(id="weather", name="天氣小幫手", main=False, description="天氣。", rules="",
                        weather_site={"county": "臺北市", "town": "中正區"})


def test_the_members_and_handoff_rules_the_core_sends_decide_the_target():
    factory, create = _client(json.dumps({"target": "service", "clarification": "", "context": "訂單"}))
    history = [{"role": "user", "content": "我的訂單到哪了？"}]

    routed = route(_config(), "那退貨呢？", [MAIN, SERVICE],
                   HandoffContext(current_role="main", history=history), client_factory=factory)

    assert routed["target"] == "service" and routed["context"] == "訂單"
    assert routed["decided_by"] == "model"
    prompt = create.call_args.kwargs["messages"][0]["content"]
    data = json.loads(prompt[prompt.index('{"today"'):])
    assert data["current_role"] == "main"
    assert data["roles"][1] == {"id": "service", "name": "客服小幫手", "main": False,
                                "description": "回答會員、訂單與退換貨問題。",
                                "rules": "會員或訂單問題交給客服。", "tools": []}
    assert create.call_args.kwargs["messages"][1:] == [*history, {"role": "user", "content": "那退貨呢？"}]


def test_a_weather_question_uses_the_site_location_the_core_sends():
    factory, create = _client("{}")

    routed = route(_config(), "臺北市明天天氣如何？", [MAIN, WEATHER],
                   HandoffContext(current_role="main"), client_factory=factory)

    assert routed["target"] == "weather" and routed["decided_by"] == "keyword"
    assert routed["county"] == "臺北市"
    create.assert_not_called()


def test_the_visitor_location_comes_from_this_conversation_only():
    decision = {"target": "weather", "clarification": "", "county": "臺南市", "town": "東區",
                "kind": "forecast", "start_date": "", "end_date": "", "context": ""}
    factory, _ = _client(json.dumps(decision, ensure_ascii=False))

    confirmed = route(_config(), "那週末呢？", [MAIN, WEATHER],
                      HandoffContext(current_role="weather", confirmed={"county": "臺南市", "town": "東區"}),
                      client_factory=factory)
    fresh = route(_config(), "那週末呢？", [MAIN, WEATHER],
                  HandoffContext(current_role="weather"), client_factory=factory)

    assert (confirmed["county"], confirmed["town"]) == ("臺南市", "東區")
    # Without this conversation's confirmed place, a guessed county is refused.
    assert fresh["target"] is None and fresh["county"] == ""


def test_an_unusable_decision_is_a_routing_error_of_the_llm_layer():
    factory, _ = _client("not json")

    with pytest.raises(RoutingError):
        route(_config(), "你好", [MAIN, SERVICE], HandoffContext(current_role="main"), client_factory=factory)
