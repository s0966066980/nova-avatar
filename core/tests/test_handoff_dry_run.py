# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Console handoff dry run: the saved composition routes a test question, nothing else happens."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nova_llm.handoff import CLARIFY, route_schema
from nova_core.profiles.routing import route_question
from nova_core.profiles.store import ProfileError
from llm_fakes import FakeLlm
from role_fakes import _config, _prompt, _schema, composition
from composition_fakes import _request, composition_routes, store  # noqa: F401

DRY_RUN = "/api/profiles/composition/dry-run"


def _enable(store, *members):  # noqa: F811
    library = store.load()
    _request("PUT", "/api/profiles/composition",
             {"expected_revision": library["composition"]["revision"], "enabled": True})
    for pid in members:
        composition = store.load()["composition"]
        _request("POST", "/api/profiles/composition/members",
                 {"expected_revision": composition["revision"],
                  "member": {"profile_id": pid, "enabled": True, "description": f"{pid} 的專長",
                             "rules": f"問到 {pid} 時交給它", "announcement": f"請{pid}回答。"}})


@pytest.fixture
def routes(composition_routes):  # noqa: F811
    return composition_routes


def test_dry_run_routes_with_the_saved_composition_and_a_fresh_conversation(routes, monkeypatch):
    store = routes
    _enable(store, "s1")
    calls = []

    def fake_route(config, library, current_id, text, history, confirmed, **options):
        calls.append(dict(library=library, current_id=current_id, text=text, history=history,
                          confirmed=confirmed, options=options, model=config.llm.model))
        return {"target": "s1", "clarification": "", "context": "", "county": "", "town": "",
                "kind": "", "start_date": "", "end_date": "", "decided_by": "model", "reason": "s1 的專長"}

    monkeypatch.setattr("nova_core.server.routes.profiles.route_question", fake_route)
    before = store.load()
    status, body = _request("POST", DRY_RUN, {"current_profile_id": "weather", "text": "  問到 s1  "})
    assert status == 200, body
    assert body["target"] == "s1" and body["target_name"] == "專門1" and body["handoff"] is True
    assert body["reason"] == "s1 的專長" and body["decided_by"] == "model"
    assert body["revision"] == before["revision"]
    call, = calls
    assert (call["current_id"], call["text"], call["history"], call["confirmed"]) == ("weather", "問到 s1", [], {})
    assert call["options"]["explain"] is True
    assert call["library"]["composition"] == before["composition"]
    # Nothing is saved, spoken or remembered.
    assert store.load() == before


def test_dry_run_reports_clarify_and_staying_with_the_current_role(routes, monkeypatch):
    _enable(routes, "s1")
    replies = iter([{"target": None, "clarification": "請問想先問哪一個？", "reason": "混合主題"},
                    {"target": "main", "clarification": "", "reason": "一般問題"}])

    def fake_route(*_args, **_options):
        return {"context": "", "county": "", "town": "", "kind": "", "start_date": "", "end_date": "",
                "decided_by": "model", **next(replies)}

    monkeypatch.setattr("nova_core.server.routes.profiles.route_question", fake_route)
    status, body = _request("POST", DRY_RUN, {"current_profile_id": "main", "text": "天氣和訂單"})
    assert status == 200
    assert (body["target"], body["target_name"], body["handoff"]) == (None, "", False)
    assert body["clarification"] == "請問想先問哪一個？"
    status, body = _request("POST", DRY_RUN, {"current_profile_id": "main", "text": "你好"})
    assert (body["target"], body["handoff"]) == ("main", False)


def test_dry_run_uses_the_keyword_pre_filter_without_a_model(routes):
    _enable(routes)
    status, body = _request("POST", DRY_RUN, {"current_profile_id": "main", "text": "臺北市明天天氣如何"})
    assert status == 200, body
    assert (body["target"], body["decided_by"]) == ("weather", "keyword")
    assert "關鍵字" in body["reason"] and body["weather"]["county"] == "臺北市"


@pytest.mark.parametrize("payload, enable, status, message", [
    ({"current_profile_id": "main", "text": "你好"}, False, 409, "角色交接"),
    ({"current_profile_id": "s7", "text": "你好"}, True, 400, "目前角色"),
    ({"current_profile_id": "main", "text": "   "}, True, 400, "測試問題"),
    ({"current_profile_id": "main", "text": "長" * 501}, True, 400, "測試問題"),
    ({"text": "你好"}, True, 400, "目前角色"),
])
def test_dry_run_rejects_what_it_cannot_route(routes, payload, enable, status, message):
    if enable:
        _enable(routes)
    got, body = _request("POST", DRY_RUN, payload)
    assert got == status and message in body["msg"]


def test_an_unreachable_model_is_reported_as_unavailable(routes, monkeypatch):
    _enable(routes, "s1")

    def broken(*_args, **_options):
        raise ConnectionError("refused")

    monkeypatch.setattr("nova_core.server.routes.profiles.route_question", broken)
    status, body = _request("POST", DRY_RUN, {"current_profile_id": "main", "text": "你好"})
    assert status == 503 and "模型" in body["msg"]


def _route(library, current, text, decision, *, explain=False):
    raw = json.dumps(decision, ensure_ascii=False)
    create = Mock(return_value=SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=raw))]))

    class Client:
        def __init__(self, **_):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

        def close(self):
            pass

    return route_question(_config(), library, current, text, [], {}, llm=FakeLlm(routing_client_factory=Client),
                          explain=explain), create


def test_explain_adds_a_reason_after_every_decision_field():
    for weather in (False, True):
        plain, explained = route_schema(["main", "s1"], weather), route_schema(["main", "s1"], weather, explain=True)
        assert "reason" not in plain["properties"]
        assert explained["required"] == [*plain["required"], "reason"]
        assert list(explained["properties"])[0] == "target"
    library = composition()
    _, create = _route(library, "main", "你好", {"target": "main"}, explain=True)
    assert "reason" in _prompt(create) and "reason" in _schema(create)["properties"]
    _, create = _route(library, "main", "你好", {"target": "main"})
    assert "reason" not in _prompt(create) and "reason" not in _schema(create)["properties"]


def test_explained_decisions_return_the_models_reason():
    library = composition()
    result, _ = _route(library, "main", "訂單到了嗎", {"target": "service", "reason": "訂單屬於客服"}, explain=True)
    assert (result["target"], result["reason"]) == ("service", "訂單屬於客服")
    result, _ = _route(library, "main", "訂單到了嗎", {"target": "service", "reason": "多餘"})
    assert "reason" not in result


def test_an_unconfirmed_weather_place_replaces_the_models_reason():
    result, _ = _route(composition(), "main", "那裡天氣如何",
                       {"target": "weather", "county": "高雄市", "reason": "天氣問題"}, explain=True)
    assert result["target"] is None and "地點" in result["reason"]


def test_conversations_route_without_a_reason():
    result, _ = _route(composition(), "main", "你好", {"target": CLARIFY, "clarification": "請再說一次"})
    assert result["target"] is None and "reason" not in result
    with pytest.raises(ProfileError):
        _route(composition(), "main", "你好", {"target": "unknown"})
