# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Keyword pre-filter in front of the small routing model (ticket 17)."""
from __future__ import annotations

import json
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.config.schema import Config
from src.profiles.routing import route_question
from src.profiles.store import ProfileStore
from src.profiles.weather import COUNTIES, TAIPEI
from src.profiles.weather_keywords import PLACES, canonical_county, explicit_counties, keyword_route

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
    # Names a city, but is not a weather question.
    "Tell me a fun fact about Taipei.",
    "Tell me a fun fact about Taiwan.",
    "Are there hot springs near Taipei?",
    "How do I visit Rainbow Village in Taichung?",
    "Which university in Tainan offers degrees in design?",
    "臺北市有什麼好吃的？",
    "介紹一下高雄的景點",
    "比較台北和高雄的公司服務",
    "請介紹一下你們的服務。",
    # Weather, but no county: the model or a clarification decides.
    "明天會下雨嗎？",
    "那週末呢？",
    "What can you help me with?",
])
def test_question_without_both_weather_and_one_county_is_left_to_the_model(text):
    assert keyword_route(text, FRIDAY) is None


@pytest.mark.parametrize("text", [
    "新竹明天的天氣",                      # city or county?
    "What's the weather in Chiayi tomorrow?",
    "Will it rain in Taipei or Tainan tomorrow?",
    "臺北市中正區明天的天氣",              # a district the table cannot validate
    "中正區明天會下雨嗎",
    "Will it rain in Da'an District, Taipei tomorrow?",
    "下週三臺北會下雨嗎",                  # a date the table does not resolve
    "Will it rain in Taipei next Monday?",
    "Taipei weather on 11/3",
    "明天臺北天氣如何？也介紹一下你們的服務",  # mixed topics need a clarification
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


# route_question wiring


def _route(text, model_decision=None, *, history=(), weather_tool=True):
    config = Config()
    config.llm.provider = "llamacpp"
    config.llm.base_url = "http://127.0.0.1:18080/v1"
    library = ProfileStore(Path(tempfile.mkdtemp()) / "profiles.yaml").initialize(config)
    specialist = next(p for p in library["profiles"] if p["id"] == library["pair"]["specialist"])
    specialist["tools"]["weather"] = weather_tool
    raw = json.dumps(model_decision or {"route": "answer"}, ensure_ascii=False)
    create = Mock(return_value=SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=raw))]))

    class Client:
        def __init__(self, **_):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

        def close(self):
            pass

    routed = route_question(config, library, library["pair"]["main"], text, list(history), {},
                            client_factory=Client)
    return routed, create


def test_english_weather_question_hands_off_without_the_model_after_a_long_history():
    # The measured failure: after ten history messages E2B answered
    # specialist with an empty county, so the turn never handed off.
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
    # E2B wrote "臺南" for Tainan, which failed validation and asked again.
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
