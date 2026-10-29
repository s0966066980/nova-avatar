# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Keyword pre-filter for weather handoffs, ahead of the small routing model.

Gemma 4 E2B often leaves ``county`` empty or writes it without its suffix
(``臺南``) for English place names, so a clear weather question about one
county is decided here. Anything less certain (no weather word, no county,
an ambiguous name, a district, an unresolved date or a second topic) returns
``None`` and the model decides as before.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import re
from typing import Mapping, Optional


@dataclass(frozen=True)
class Place:
    county: str
    names: tuple[str, ...]  # Chinese, English, pinyin and common aliases


# A name listed under two counties (新竹, Chiayi) is ambiguous and never
# chosen on its own. 台 is normalised to 臺 before matching.
PLACES = (
    Place("臺北市", ("臺北市", "臺北", "taipei city", "taipei", "taibei")),
    Place("新北市", ("新北市", "新北", "臺北縣", "new taipei city", "new taipei", "taipei county", "xinbei")),
    Place("基隆市", ("基隆市", "基隆", "keelung", "jilong")),
    Place("桃園市", ("桃園市", "桃園", "桃園縣", "taoyuan")),
    Place("新竹市", ("新竹市", "新竹", "hsinchu city", "hsinchu", "xinzhu city", "xinzhu")),
    Place("新竹縣", ("新竹縣", "新竹", "hsinchu county", "hsinchu", "xinzhu county", "xinzhu")),
    Place("苗栗縣", ("苗栗縣", "苗栗", "miaoli")),
    Place("臺中市", ("臺中市", "臺中", "臺中縣", "taichung", "taizhong")),
    Place("彰化縣", ("彰化縣", "彰化", "changhua", "zhanghua")),
    Place("南投縣", ("南投縣", "南投", "nantou")),
    Place("雲林縣", ("雲林縣", "雲林", "yunlin")),
    Place("嘉義市", ("嘉義市", "嘉義", "chiayi city", "chiayi", "jiayi city", "jiayi")),
    Place("嘉義縣", ("嘉義縣", "嘉義", "chiayi county", "chiayi", "jiayi county", "jiayi")),
    Place("臺南市", ("臺南市", "臺南", "臺南縣", "tainan")),
    Place("高雄市", ("高雄市", "高雄", "高雄縣", "kaohsiung", "gaoxiong")),
    Place("屏東縣", ("屏東縣", "屏東", "pingtung", "pingdong")),
    Place("宜蘭縣", ("宜蘭縣", "宜蘭", "yilan", "ilan")),
    Place("花蓮縣", ("花蓮縣", "花蓮", "hualien", "hualian")),
    Place("臺東縣", ("臺東縣", "臺東", "taitung", "taidong")),
    Place("澎湖縣", ("澎湖縣", "澎湖", "penghu", "pescadores")),
    Place("金門縣", ("金門縣", "金門", "kinmen", "jinmen", "quemoy")),
    Place("連江縣", ("連江縣", "連江", "馬祖", "lienchiang", "lianjiang", "matsu", "mazu")),
)

# Weather words. Bare "hot", "cold" or "degree" also name hot springs and
# university degrees, so only phrases are listed for them.
WEATHER_TERMS = (
    "天氣", "氣溫", "溫度", "氣象", "預報", "下雨", "降雨", "雨量", "有雨", "雷雨", "大雨", "豪雨",
    "陣雨", "雨天", "下雪", "颱風", "晴天", "陰天", "多雲", "濕度", "紫外線", "寒流", "鋒面", "帶傘",
    "冷不冷", "熱不熱", "幾度",
    "weather", "forecast", "forecasts", "rain", "rains", "raining", "rainy", "rainfall",
    "temperature", "temperatures", "humid", "humidity", "typhoon", "typhoons", "sunny", "cloudy",
    "snow", "snowing", "storm", "storms", "stormy", "thunderstorm", "thunderstorms", "drizzle",
    "windy", "foggy", "umbrella", "how hot", "how cold", "how warm",
)

# Day offsets from today; "weekend" resolves to the coming Saturday–Sunday.
DATE_PHRASES = {
    "今天": 0, "今日": 0, "今晚": 0, "明天": 1, "明日": 1, "後天": 2, "大後天": 3,
    "today": 0, "tonight": 0, "tomorrow": 1, "day after tomorrow": 2,
    "週末": "weekend", "這週末": "weekend", "本週末": "weekend", "周末": "weekend",
    "this weekend": "weekend", "weekend": "weekend",
}
CURRENT_PHRASES = ("現在", "目前", "此刻", "此時", "right now", "now", "currently", "at the moment")

# Left to the model: dates the table above does not resolve, districts it
# cannot validate, and a second topic that needs a clarification.
_UNRESOLVED_DATE = re.compile(
    r"[0-9０-９]|下週|下周|下禮拜|下星期|星期|禮拜|[週周][一二三四五六日天]|這週|本週|未來|幾天|七天|一週"
    r"|昨天|前天|[一二三四五六七八九十]+[月號日]"
    r"|\b(?:next|week|weeks|days|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r"|january|february|march|april|june|july|august|september|october|november|december)\b")
_DISTRICT = re.compile(r"[一-鿿][區鄉鎮市]|\b(?:district|township|village)\b")
SECOND_TOPIC = ("順便", "另外", "以及", "還有", "介紹", "服務",
                "also", "by the way", "as well as", "service", "services")
_SENTENCE_END = re.compile(r"[。？！?!；;]+")


def _normalise(text: str) -> str:
    return text.replace("台", "臺").lower()


def _pattern(phrase: str) -> str:
    # Latin phrases match whole words; Chinese phrases have no word breaks.
    if phrase.isascii():
        return r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])"
    return re.escape(phrase)


def _index(phrases):
    return sorted(((p, re.compile(_pattern(p))) for p in phrases), key=lambda item: -len(item[0]))


def _aliases() -> dict[str, frozenset[str]]:
    aliases: dict[str, frozenset[str]] = {}
    for place in PLACES:
        for name in map(_normalise, place.names):
            aliases[name] = aliases.get(name, frozenset()) | {place.county}
    return aliases


_ALIASES = _aliases()
_PLACE_PATTERNS = _index(_ALIASES)
_WEATHER = [pattern for _, pattern in _index(WEATHER_TERMS)]
_DATES = _index(DATE_PHRASES)
_CURRENT = [pattern for _, pattern in _index(CURRENT_PHRASES)]
_TOPICS = [pattern for _, pattern in _index(SECOND_TOPIC)]


def _take(text: str, patterns) -> tuple[list[str], str]:
    """Phrases found longest first; each match is blanked so a shorter one cannot reuse it."""
    found = []
    for phrase, pattern in patterns:
        if pattern.search(text):
            found.append(phrase)
            text = pattern.sub(" ", text)
    return found, text


def _places(text: str) -> tuple[list[frozenset[str]], str]:
    names, rest = _take(_normalise(text), _PLACE_PATTERNS)
    return [_ALIASES[name] for name in names], rest


def explicit_counties(text: str) -> set[str]:
    """Every county a visitor's words could mean; an ambiguous name adds all of its counties."""
    matches, _ = _places(text)
    return set().union(*matches)


def canonical_county(name: str) -> str:
    """The official county for one name (``臺南``, ``Tainan``), or '' when unknown or ambiguous."""
    counties = _ALIASES.get(_normalise(name.strip()), frozenset())
    return next(iter(counties)) if len(counties) == 1 else ""


def _date_range(offset, today: date) -> tuple[date, date]:
    if offset != "weekend":
        day = today + timedelta(days=offset)
        return day, day
    if today.weekday() == 6:
        return today, today
    saturday = today + timedelta(days=(5 - today.weekday()) % 7)
    return saturday, saturday + timedelta(days=1)


def keyword_route(text: str, today: date, *, confirmed: Optional[Mapping] = None,
                  site: Optional[Mapping] = None) -> Optional[dict]:
    """A weather-role decision for a clear weather question about one county, else None."""
    if len([part for part in _SENTENCE_END.split(text) if part.strip()]) > 1:
        return None
    matches, rest = _places(text)
    if len(matches) != 1 or len(matches[0]) != 1:
        return None
    lowered = _normalise(text)
    if not any(pattern.search(lowered) for pattern in _WEATHER):
        return None
    if any(pattern.search(rest) for pattern in _TOPICS) or _DISTRICT.search(rest):
        return None
    dates, rest = _take(rest, _DATES)
    current = any(pattern.search(rest) for pattern in _CURRENT)
    if len(dates) > 1 or _UNRESOLVED_DATE.search(rest):
        return None
    offset = DATE_PHRASES[dates[0]] if dates else 0
    if current and offset != 0:
        return None
    start, end = _date_range(offset, today)
    county = next(iter(matches[0]))
    town = ""
    for known in (confirmed or {}, site or {}):
        if known.get("county") == county and known.get("town"):
            town = known["town"]
            break
    return {"route": "specialist", "clarification": "", "county": county, "town": town,
            "kind": "current" if current else "forecast",
            "start_date": start.isoformat(), "end_date": end.isoformat(), "context": ""}
