# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""N-way routing: any enabled member, including the main avatar, answers a turn (ticket 02)."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.profiles.routing import candidates, route_question, weather_member
from src.profiles.store import ProfileError
from src.profiles.weather import TAIPEI
from tests.role_fakes import async_test, connect, field  # noqa: F401
from tests.role_fakes import SERVICE, TRAFFIC, _config, _member, _prompt, _schema, composition  # noqa: F401


def _route(library, current, text, decision, *, history=(), confirmed=None, config=None):
    raw = json.dumps(decision, ensure_ascii=False)
    create = Mock(return_value=SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=raw))]))

    class Client:
        def __init__(self, **_):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

        def close(self):
            pass

    routed = route_question(config or _config(), library, current, text, list(history),
                            confirmed or {}, client_factory=Client)
    return routed, create


def _data(create):
    """The JSON data block the contract is followed by."""
    return next(json.loads(line) for line in _prompt(create).splitlines() if line.startswith('{"today"'))


# ── Candidates and prompt ─────────────────────────────────────────────────

def test_candidates_are_the_main_avatar_then_live_members_in_order():
    library = composition()
    assert candidates(library) == ["main", "weather", "service", "traffic"]
    assert weather_member(library)["profile_id"] == "weather"
    library["composition"]["enabled"] = False
    assert candidates(library) == ["main"]
    assert weather_member(library) is None


def test_prompt_lists_every_enabled_member_with_its_texts_and_marks_the_current_role():
    library = composition()
    history = [{"role": "user", "content": "我的訂單到哪了？"},
               {"role": "assistant", "content": "您的訂單已出貨。"}]
    routed, create = _route(library, "service", "那退貨呢？", {"target": "service"}, history=history)

    assert routed["target"] == "service"
    data = _data(create)
    assert data["current_role"] == "service"
    roles = {role["id"]: role for role in data["roles"]}
    assert list(roles) == ["main", "weather", "service", "traffic"]
    assert roles["main"]["main"] is True and roles["main"]["description"] == "公司簡介與一般問題。"
    assert roles["service"] == {"id": "service", "name": "客服小幫手", "main": False,
                                "description": SERVICE, "rules": "會員或訂單問題交給客服。",
                                "tools": []}
    assert roles["weather"]["tools"] == ["weather"]
    assert "停用角色" not in _prompt(create)
    # The current role's recent conversation precedes the question.
    messages = create.call_args.kwargs["messages"]
    assert messages[1:] == [*history, {"role": "user", "content": "那退貨呢？"}]
    # A continuing follow-up stays; switching topic hands off; mixed topics ask first.
    assert "追問" in _prompt(create) and "clarify" in _prompt(create)


def test_schema_enumerates_the_candidate_ids_and_clarify_with_target_first():
    _, create = _route(composition(), "main", "你好", {"target": "main"})
    schema = _schema(create)
    assert schema["properties"]["target"]["enum"] == ["main", "weather", "service", "traffic", "clarify"]
    assert schema["required"][0] == "target"
    assert {"county", "town", "kind", "start_date", "end_date"} <= set(schema["properties"])


def test_without_a_weather_member_the_prompt_and_schema_carry_no_weather():
    library = composition(weather=False)
    routed, create = _route(library, "main", "明天臺北市會下雨嗎？", {"target": "main"})
    # No keyword pre-filter without a weather tool: the model decided.
    create.assert_called_once()
    assert routed["target"] == "main" and routed["decided_by"] == "model"
    schema = _schema(create)
    assert set(schema["properties"]) == {"target", "clarification", "context"}
    prompt = _prompt(create)
    assert "天氣" not in prompt and "county" not in prompt
    assert "site_location" not in _data(create)


def test_a_disabled_weather_holder_turns_the_weather_routing_off():
    library = composition()
    library["composition"]["members"][0]["enabled"] = False
    routed, create = _route(library, "main", "明天臺北市會下雨嗎？", {"target": "main"})
    create.assert_called_once()
    assert "county" not in _schema(create)["properties"]
    assert routed["target"] == "main"


# ── Decisions ─────────────────────────────────────────────────────────────

def test_one_specialist_hands_off_directly_to_another():
    routed, _ = _route(composition(), "service", "停車場在哪裡？",
                       {"target": "traffic", "context": "訪客想知道停車場位置"})
    assert routed["target"] == "traffic"
    assert routed["context"] == "訪客想知道停車場位置"
    assert routed["county"] == routed["town"] == routed["kind"] == ""
    assert routed["decided_by"] == "model" and routed["accepted_at"]


def test_clarify_has_no_target_and_keeps_its_question():
    routed, _ = _route(composition(), "service", "停車場在哪？也想問退貨。",
                       {"target": "clarify", "clarification": "請問您想先問停車還是退貨？"})
    assert routed["target"] is None
    assert routed["clarification"] == "請問您想先問停車還是退貨？"


@pytest.mark.parametrize("target", ["archive", "unknown", "", None])
def test_a_target_outside_the_live_members_is_rejected(target):
    with pytest.raises(ProfileError):
        _route(composition(), "main", "你好", {"target": target})


def test_weather_fields_are_cleared_for_a_target_without_the_weather_tool():
    routed, _ = _route(composition(), "weather", "比較台北和高雄的客服",
                       {"target": "service", "county": "臺北市", "town": "中正區", "kind": "forecast"})
    assert routed["target"] == "service"
    assert (routed["county"], routed["town"], routed["kind"]) == ("", "", "")


def test_weather_target_is_validated_against_the_holders_site():
    library = composition()
    library["composition"]["members"][0]["tools"]["weather"].update(county="臺南市", town="安平區")
    routed, _ = _route(library, "service", "附近適合散步嗎？",
                       {"target": "weather", "county": "臺南市", "town": "安平區", "kind": "forecast"})
    assert (routed["target"], routed["county"], routed["town"]) == ("weather", "臺南市", "安平區")
    assert routed["start_date"] == datetime.now(TAIPEI).date().isoformat()


def test_keyword_pre_filter_sends_weather_to_the_holder_from_any_current_role():
    tomorrow = (datetime.now(TAIPEI).date() + timedelta(days=1)).isoformat()
    for current in ("main", "service", "traffic", "weather"):
        routed, create = _route(composition(), current, "明天臺北市會下雨嗎？", {"target": "main"})
        create.assert_not_called()
        assert routed["target"] == "weather" and routed["decided_by"] == "keyword"
        assert (routed["county"], routed["start_date"], routed["context"]) == ("臺北市", tomorrow, "")


def test_english_clarification_follows_the_conversation_locale():
    config = _config()
    config.conversation.locale = "en-US"
    _, create = _route(composition(), "main", "Hi", {"target": "main"}, config=config)
    assert "Return clarification in English." in _prompt(create)


# ── Runtime plans (ADR 0022) ──────────────────────────────────────────────

def _connect_with_members(field, router=None, current="main"):  # noqa: F811
    """A conversation with main, weather, 客服 and 交通, at ``current``, inside turn "t"."""
    library = field.library
    library["composition"]["enabled"] = True
    _member(library, "service", "客服小幫手", SERVICE)
    _member(library, "traffic", "交通嚮導", TRAFFIC)
    if router is not None:
        field.router = router
    voice, _ = connect(field)
    roles = voice._role_coordinator
    roles._bind(voice, current)
    roles.current_id = current
    voice._turn_id = "t"
    voice._start_turn_context("t")
    return voice, roles


@pytest.mark.parametrize("current,plan", [
    ("main", {"context": "本輪未取得即時氣象資料，不可提供實際即時天氣數值。"}),
    ("service", {"context": "本輪未取得即時氣象資料，不可提供實際即時天氣數值。"}),
    ("weather", {"weather": None, "context": ""}),
])
@async_test
async def test_speculative_plan_depends_on_whether_the_current_role_holds_the_weather_tool(
        field, current, plan):  # noqa: F811
    voice, roles = _connect_with_members(field, current=current)
    try:
        assert roles.speculative_plan() == plan
    finally:
        await voice.close()


@async_test
async def test_staying_with_a_non_weather_specialist_releases_the_speculative_answer(field):  # noqa: F811
    voice, roles = _connect_with_members(
        field, Mock(return_value={"target": "service", "context": "訪客追問退貨"}), "service")
    try:
        plan = await roles.before_generate(voice, "那退貨呢？", "t", voice._generation)
        assert plan == roles.speculative_plan()
    finally:
        await voice.close()


@async_test
async def test_router_clarify_is_spoken_as_a_fixed_reply(field):  # noqa: F811
    voice, roles = _connect_with_members(
        field, Mock(return_value={"target": None, "clarification": "請問您想先問哪一項？"}))
    try:
        plan = await roles.before_generate(voice, "停車與退貨", "t", voice._generation)
        assert plan == {"fixed": "請問您想先問哪一項？"}
    finally:
        await voice.close()
