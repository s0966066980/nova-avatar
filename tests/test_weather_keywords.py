# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Keyword pre-filter and two-stage lightweight gate tests for Jetson Orin."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.config.schema import Config
from src.weather import (
    COUNTIES,
    PLACES,
    TAIPEI,
    canonical_county,
    explicit_counties,
    fast_weather_route,
    has_weather_cue,
    keyword_route,
    resolve_weather_plan,
    route_question,
)

FRIDAY = date(2026, 10, 30)


def _day(offset):
    return (FRIDAY + timedelta(days=offset)).isoformat()


def test_place_table_covers_every_county_exactly_once():
    assert sorted(place.county for place in PLACES) == sorted(COUNTIES)


@pytest.mark.parametrize("text,county,kind,start,end", [
    ("Will it rain in Taipei tomorrow?", "臺北市", "forecast", 1, 1),
    ("What is the weather forecast for Tainan this weekend?", "臺南市", "forecast", 1, 2),
    ("How hot will it be in Kaohsiung tomorrow?", "高雄市", "forecast", 1, 1),
    ("Is it raining in Gaoxiong right now?", "高雄市", "current", 0, 0),
    ("Taibei weather today", "臺北市", "forecast", 0, 0),
    ("What's the temperature in New Taipei City tomorrow?", "新北市", "forecast", 1, 1),
    ("Will there be a typhoon in Matsu the day after tomorrow?", "連江縣", "forecast", 2, 2),
    ("Hsinchu City weather tomorrow", "新竹市", "forecast", 1, 1),
    ("明天臺北市會下雨嗎？", "臺北市", "forecast", 1, 1),
    ("高雄市這週末天氣如何？", "高雄市", "forecast", 1, 2),
    ("臺中市明天氣溫幾度？", "臺中市", "forecast", 1, 1),
    ("今天台北天氣如何？", "臺北市", "forecast", 0, 0),
    ("台東後天會下雨嗎", "臺東縣", "forecast", 2, 2),
    ("馬祖現在天氣如何", "連江縣", "current", 0, 0),
    ("花蓮天氣", "花蓮縣", "forecast", 0, 0),
])
def test_weather_question_naming_one_county_goes_to_the_weather_role(text, county, kind, start, end):
    decision = keyword_route(text, FRIDAY)
    assert decision == {"route": "specialist", "clarification": "", "county": county, "town": "",
                        "kind": kind, "start_date": _day(start), "end_date": _day(end), "context": ""}


@pytest.mark.parametrize("text", [
    "Tell me a fun fact about Taipei.",
    "Tell me a fun fact about Taiwan.",
    "Are there hot springs near Taipei?",
    "How do I visit Rainbow Village in Taichung?",
    "Which university in Tainan offers degrees in design?",
    "臺北市有什麼好吃的？",
    "介紹一下高雄的景點",
    "比較台北和高雄的公司服務",
    "請介紹一下你們的服務。",
    "明天會下雨嗎？",
    "那週末呢？",
    "What can you help me with?",
])
def test_question_without_both_weather_and_one_county_is_left_to_the_model(text):
    assert keyword_route(text, FRIDAY) is None


@pytest.mark.parametrize("text", [
    "新竹明天的天氣",
    "What's the weather in Chiayi tomorrow?",
    "Will it rain in Taipei or Tainan tomorrow?",
    "臺北市中正區明天的天氣",
    "中正區明天會下雨嗎",
    "Will it rain in Da'an District, Taipei tomorrow?",
    "下週三臺北會下雨嗎",
    "Will it rain in Taipei next Monday?",
    "Taipei weather on 11/3",
    "明天臺北天氣如何？也介紹一下你們的服務",
    "Will it rain in Taipei tomorrow? Also, what services do you offer?",
])
def test_ambiguous_place_district_date_or_mixed_topic_is_left_to_the_model(text):
    assert keyword_route(text, FRIDAY) is None


def test_a_confirmed_district_is_kept_for_the_same_county_only():
    confirmed = {"county": "臺北市", "town": "中正區"}
    assert keyword_route("臺北市明天會下雨嗎", FRIDAY, confirmed=confirmed)["town"] == "中正區"
    assert keyword_route("高雄市明天會下雨嗎", FRIDAY, confirmed=confirmed)["town"] == ""
    site = {"county": "高雄市", "town": "前鎮區"}
    assert keyword_route("高雄市明天會下雨嗎", FRIDAY, site=site)["town"] == "前鎮區"


def test_weekend_on_a_saturday_or_sunday_starts_today():
    assert keyword_route("Tainan weather this weekend", date(2026, 10, 31))["start_date"] == "2026-10-31"
    sunday = keyword_route("臺南週末天氣", date(2026, 11, 1))
    assert (sunday["start_date"], sunday["end_date"]) == ("2026-11-01", "2026-11-01")


@pytest.mark.parametrize("text,expected", [
    ("What is the weather in Taipei today?", {"臺北市"}),
    ("Compare New Taipei and Taipei.", {"新北市", "臺北市"}),
    ("New Taipei City tomorrow", {"新北市"}),
    ("Hsinchu tomorrow", {"新竹市", "新竹縣"}),
    ("Hsinchu City tomorrow", {"新竹市"}),
    ("今天台北天氣如何？", {"臺北市"}),
    ("新北市和臺北市", {"新北市", "臺北市"}),
    ("新竹明天的天氣", {"新竹市", "新竹縣"}),
    ("中正區明天會下雨嗎", set()),
])
def test_explicit_counties_lists_every_county_a_name_could_mean(text, expected):
    assert explicit_counties(text) == expected


@pytest.mark.parametrize("name,county", [
    ("臺南", "臺南市"), ("台南市", "臺南市"), ("Tainan", "臺南市"), ("臺南市", "臺南市"),
    ("新竹", ""), ("火星", ""), ("", ""),
])
def test_canonical_county_maps_only_one_unambiguous_name(name, county):
    assert canonical_county(name) == county


def _default_library(*, weather_tool=True):
    return {
        "weather": {"county": "", "town": ""},
        "pair": {"main": "main", "specialist": "weather-specialist"},
        "profiles": [
            {"id": "main", "name": "預設助手", "summary": "一般問答", "tools": {"weather": False}},
            {"id": "weather-specialist", "name": "氣象專家", "summary": "天氣與氣象", "tools": {"weather": weather_tool}},
        ],
    }


def _route(text, model_decision=None, *, history=(), weather_tool=True):
    config = Config()
    config.llm.provider = "llamacpp"
    config.llm.base_url = "http://127.0.0.1:18080/v1"
    library = _default_library(weather_tool=weather_tool)
    raw = json.dumps(model_decision or {"route": "answer"}, ensure_ascii=False)
    create = Mock(return_value=SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=raw))]))

    class Client:
        def __init__(self, **_):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

        def close(self):
            pass

    routed = route_question(config, library, "main", text, list(history), {},
                            client_factory=Client)
    return routed, create


def test_english_weather_question_hands_off_without_the_model_after_a_long_history():
    history = [{"role": "user", "content": "規律運動有什麼好處？"},
               {"role": "assistant", "content": "可以增強心肺功能。"}] * 5
    routed, create = _route("Will it rain in Taipei tomorrow?",
                            {"route": "specialist", "county": ""}, history=history)
    tomorrow = (datetime.now(TAIPEI).date() + timedelta(days=1)).isoformat()
    assert (routed["route"], routed["county"], routed["start_date"]) == ("specialist", "臺北市", tomorrow)
    assert routed["accepted_at"]
    create.assert_not_called()


def test_non_weather_question_naming_a_city_still_asks_the_model():
    routed, create = _route("Tell me a fun fact about Taipei.", {"route": "answer"})
    assert routed["route"] == "answer"
    create.assert_called_once()


def test_pre_filter_is_off_when_the_specialist_has_no_weather_tool():
    routed, create = _route("Will it rain in Taipei tomorrow?", {"route": "answer"}, weather_tool=False)
    assert routed["route"] == "answer"
    create.assert_called_once()


def test_model_county_without_its_suffix_is_canonicalised():
    routed, _ = _route("Is tomorrow good for hiking in Tainan?",
                       {"route": "specialist", "county": "臺南", "kind": "forecast"})
    assert (routed["route"], routed["county"]) == ("specialist", "臺南市")


def test_model_empty_county_is_filled_from_the_one_county_the_visitor_named():
    routed, _ = _route("Is tomorrow good for hiking in Kaohsiung?",
                       {"route": "specialist", "county": "", "kind": "forecast"})
    assert (routed["route"], routed["county"]) == ("specialist", "高雄市")


def test_model_empty_county_stays_empty_for_an_ambiguous_name():
    routed, _ = _route("Is tomorrow good for hiking in Hsinchu?",
                       {"route": "specialist", "county": "", "kind": "forecast"})
    assert routed["county"] == ""


def test_two_stage_gate_fast_pass_skips_llm_for_non_weather_and_clear_weather():
    config = Config()
    create = Mock()

    class Client:
        def __init__(self, **_):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

        def close(self):
            pass

    # Stage 1: Non-weather question exits in 0 ms without calling LLM
    assert has_weather_cue("請問你們公司有哪些產品？") is False
    plan = resolve_weather_plan(config, "請問你們公司有哪些產品？", [], {}, client_factory=Client)
    assert plan["route"] == "answer"
    assert plan["pure_weather"] is False
    create.assert_not_called()

    # Stage 2: Missing county without default asks clarification without calling LLM
    plan_clarify = resolve_weather_plan(config, "今天天氣如何？", [], {}, client_factory=Client)
    assert plan_clarify["route"] == "clarify"
    assert "哪個縣市" in plan_clarify["clarification"]
    create.assert_not_called()

    # Stage 2: Site default county resolves without calling LLM
    config.weather.county = "臺北市"
    config.weather.town = "信義區"
    plan_site = resolve_weather_plan(config, "今天出門要帶傘嗎？", [], {}, client_factory=Client)
    assert plan_site["route"] == "specialist"
    assert plan_site["county"] == "臺北市"
    assert plan_site["town"] == "信義區"
    assert plan_site["pure_weather"] is True
    create.assert_not_called()

    # Stage 2: Follow-up date question reuses confirmed session location without calling LLM
    confirmed = {"county": "高雄市", "town": "前鎮區", "kind": "forecast", "start_date": "2026-10-30", "end_date": "2026-10-30"}
    plan_followup = fast_weather_route("那明天呢？", FRIDAY, confirmed=confirmed)
    assert plan_followup is not None
    assert plan_followup["route"] == "specialist"
    assert plan_followup["county"] == "高雄市"
    assert plan_followup["town"] == "前鎮區"
    assert plan_followup["start_date"] == "2026-10-31"
