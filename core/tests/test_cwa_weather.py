# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Contract fixtures based on CWA's documented fields, not a live-key acceptance."""
import asyncio
import json
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nova_core.config.schema import Config
from nova_llm.engines.openai import OpenAILLM
from nova_llm.response_protocol import BoardItem, SessionBoardContext
from nova_llm.tools import weather as weather_tool
from nova_llm.tools.weather import (
    SOURCE,
    SOURCE_URL,
    TAIPEI,
    CwaWeather,
    WeatherQuery,
    WeatherUnavailable,
    cwa_key,
    normalize_forecast,
    normalize_observation,
    weather_prompt,
)

pytestmark = pytest.mark.conversation

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=TAIPEI)


def query(kind="forecast", end="2026-10-16"):
    return WeatherQuery("臺北市", "中正區", kind, "2026-10-16", end)


def forecast(*, pop="60", temperature="26", issued="2026-10-16T11:30:00+08:00"):
    def element(name, key, value, start="2026-10-16T12:00:00+08:00"):
        return {"ElementName": name, "Time": [{"StartTime": start,
                 "EndTime": (datetime.fromisoformat(start) + timedelta(hours=3)).isoformat(),
                 "ElementValue": [{key: value}]}]}
    return {"records": {"DatasetInfo": {"IssueTime": issued}, "Locations": [
        {"LocationsName": "臺北市", "Location": [{"LocationName": "中正區",
         "WeatherElement": [element("溫度", "Temperature", temperature),
                           element("3小時降雨機率", "ProbabilityOfPrecipitation", pop),
                           element("天氣現象", "Weather", "多雲")]}]}]}}


def observation(*, temperature="27.5", observed="2026-10-16T11:50:00+08:00"):
    return {"records": {"Station": [{
        "StationName": "臺北", "ObsTime": {"DateTime": observed},
        "GeoInfo": {"CountyName": "臺北市", "TownName": "中正區"},
        "WeatherElement": {"AirTemperature": temperature, "Weather": "多雲",
                          "RelativeHumidity": "-99", "WindSpeed": "X"},
    }]}}


def test_probability_keeps_its_interval_and_missing_is_not_zero():
    result = normalize_forecast(forecast(pop="-"), query(), NOW)
    assert result["status"] == "available"
    probability = result["series"]["precipitation_probability_3h"][0]
    assert probability["value"] is None
    assert probability["start"] == "2026-10-16T12:00:00+08:00"
    assert probability["end"] == "2026-10-16T15:00:00+08:00"
    assert result["series"]["temperature_c"][0]["value"] == 26
    assert "不是零" in weather_prompt(result)


def test_week_product_cannot_invent_probability_after_three_days():
    data = forecast()
    periods = data["records"]["Locations"][0]["Location"][0]["WeatherElement"][1]["Time"]
    periods.append({"StartTime": "2026-10-20T06:00:00+08:00",
                    "EndTime": "2026-10-20T18:00:00+08:00",
                    "ElementValue": [{"ProbabilityOfPrecipitation": "0"}]})
    result = normalize_forecast(data, query(end="2026-10-22"), NOW)
    assert len(result["series"]["precipitation_probability_3h"]) == 1
    assert "未提供不代表 0%" in result["probability_note"]


def test_missing_issue_time_does_not_become_fetch_time():
    data = forecast()
    del data["records"]["DatasetInfo"]
    result = normalize_forecast(data, query(), NOW)
    assert result["issued_at"] is None
    assert result["fetched_at"] == NOW.isoformat()
    assert normalize_forecast(forecast(issued="2026-10-16T02:00:00+08:00"), query(), NOW)["status"] == "stale"


def test_observation_uses_station_time_and_rejects_old_data():
    result = normalize_observation(observation(), query("current"), NOW)
    assert result["temperature_c"] == 27.5
    assert result["humidity_percent"] is None
    assert result["wind_speed_ms"] is None
    assert result["station"] == "臺北"
    assert normalize_observation(observation(observed="2026-10-16T10:00:00+08:00"), query("current"), NOW)["status"] == "stale"
    invalid = observation(temperature="-99")
    invalid["records"]["Station"][0]["WeatherElement"]["Weather"] = "X"
    assert normalize_observation(invalid, query("current"), NOW)["status"] == "not_found"


def test_locations_are_exact_and_do_not_substitute_another_town():
    other = WeatherQuery("臺北市", "中山區", "forecast", "2026-10-16", "2026-10-16")
    assert normalize_forecast(forecast(), other, NOW)["status"] == "not_found"
    assert normalize_observation(observation(), other, NOW)["status"] == "not_found"


def test_cache_does_not_cross_locations_and_expires():
    async def scenario():
        calls, tick = [], [0]
        async def transport(dataset, params):
            calls.append((dataset, params))
            return forecast()
        weather = CwaWeather(transport=transport, clock=lambda: tick[0], now=lambda: NOW)
        assert (await weather.query(query()))["status"] == "available"
        assert (await weather.query(query()))["cached"] is True
        assert len(calls) == 1
        tick[0] = 601
        await weather.query(query())
        assert len(calls) == 2
        assert calls[0][0] == "F-D0047-061"
        await weather.query(query(end="2026-10-22"))
        assert calls[-1][0] == "F-D0047-063"
    asyncio.run(scenario())


def test_the_key_comes_from_the_environment_or_the_git_excluded_config_file(monkeypatch, tmp_path):
    for name in ("NOVA_CWA_API_KEY", "CWA_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    # services/llm/scripts/configure-cwa.py writes the repository's config/cwa.env.
    assert weather_tool.CONFIG_DIR.resolve() == Path(__file__).resolve().parents[2] / "config"
    monkeypatch.setattr(weather_tool, "CONFIG_DIR", tmp_path)
    (tmp_path / "cwa.env").write_text('NOVA_CWA_API_KEY="CWA-FILE"\n', "utf-8")
    assert cwa_key() == "CWA-FILE"
    monkeypatch.setenv("NOVA_CWA_API_KEY", " CWA-ENV ")
    assert cwa_key() == "CWA-ENV"


def test_missing_key_and_out_of_range_fail_before_network(monkeypatch):
    monkeypatch.setattr("nova_llm.tools.weather.cwa_key", lambda: "")
    monkeypatch.delenv("NOVA_CWA_API_KEY", raising=False)
    monkeypatch.delenv("CWA_API_KEY", raising=False)
    async def scenario():
        weather = CwaWeather(now=lambda: NOW)
        assert (await weather.query(query()))["status"] == "missing_key"
        assert (await weather.query(query(end="2026-10-24")))["status"] == "out_of_range"
    asyncio.run(scenario())


def test_cancellation_releases_query_and_failure_does_not_poison_next_turn():
    async def scenario():
        started, blocker, calls = asyncio.Event(), asyncio.Event(), [0]
        async def transport(dataset, params):
            calls[0] += 1
            if calls[0] == 1:
                started.set()
                await blocker.wait()
            if calls[0] == 2:
                raise WeatherUnavailable("rate_limited")
            return forecast()
        weather = CwaWeather(transport=transport, now=lambda: NOW)
        task = asyncio.create_task(weather.query(query()))
        await started.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("Cancelled query was swallowed")
        assert (await weather.query(query()))["status"] == "rate_limited"
        assert (await weather.query(query()))["status"] == "available"
    asyncio.run(scenario())


def test_midnight_does_not_reinterpret_an_accepted_query_or_defeat_cache():
    async def scenario():
        calls = []
        async def transport(dataset, params):
            calls.append(dataset)
            return forecast(issued="2026-10-16T23:30:00+08:00")
        now = datetime(2026, 10, 17, 0, 1, tzinfo=TAIPEI)
        weather = CwaWeather(transport=transport, now=lambda: now)
        accepted = WeatherQuery("臺北市", "中正區", "forecast", "2026-10-16", "2026-10-16",
                                "2026-10-16T23:59:59+08:00")
        assert (await weather.query(accepted))["status"] == "available"
        later = WeatherQuery("臺北市", "中正區", "forecast", "2026-10-16", "2026-10-16",
                             "2026-10-16T23:59:59.500000+08:00")
        assert (await weather.query(later))["cached"] is True
        assert len(calls) == 1
    asyncio.run(scenario())


def test_total_weather_deadline_includes_waiting_for_the_cache_lock():
    async def scenario():
        weather = CwaWeather(now=lambda: NOW)
        await weather._lock.acquire()
        try:
            result = await asyncio.wait_for(weather.query(query()), timeout=3.5)
            assert result["status"] == "timeout"
            assert result["query_seconds"] >= 2.9
        finally:
            weather._lock.release()
    asyncio.run(scenario())


def county_forecast():
    data = forecast()
    group = data['records']['Locations'][0]
    group['LocationsName'] = '台灣'
    group['Location'][0]['LocationName'] = '臺北市'
    return data


def test_county_forecast_preserves_city_scope_and_uses_official_county_products():
    async def scenario():
        calls = []
        async def transport(dataset, params):
            calls.append((dataset, params))
            return county_forecast()
        weather = CwaWeather(transport=transport, now=lambda: NOW)
        city = WeatherQuery('臺北市', '', 'forecast', '2026-10-16', '2026-10-16')
        result = await weather.query(city)
        assert result['status'] == 'available', result
        assert result['county'] == '臺北市' and result['town'] == ''
        assert calls == [('F-D0047-089', {'LocationName': '臺北市'})]
        assert result['series']['temperature_c'][0]['value'] == 26
        assert (await weather.query(city))['cached'] is True
        await weather.query(WeatherQuery('臺北市', '', 'forecast', '2026-10-16', '2026-10-22'))
        assert calls[-1] == ('F-D0047-091', {'LocationName': '臺北市'})
        # The whole city's forecast must not be cached or relabeled as a district.
        assert (await weather.query(query()))['status'] == 'not_found'
        assert calls[-1] == ('F-D0047-061', {'LocationName': '中正區'})
    asyncio.run(scenario())


def test_county_current_weather_identifies_the_actual_observation_station():
    async def scenario():
        async def transport(dataset, params):
            assert dataset == 'O-A0003-001'
            data = observation()
            # A newer mountain station must not silently replace the city's
            # own named station while that station's data is still fresh.
            mountain = observation(temperature='19', observed='2026-10-16T11:59:00+08:00')['records']['Station'][0]
            mountain['StationName'] = '陽明山'
            mountain['GeoInfo']['TownName'] = '北投區'
            data['records']['Station'].append(mountain)
            return data
        weather = CwaWeather(transport=transport, now=lambda: NOW)
        result = await weather.query(WeatherQuery('臺北市', '', 'current', '2026-10-16', '2026-10-16'))
        assert result['status'] == 'available', result
        assert result['town'] == ''
        assert result['station'] == '臺北'
        assert result['station_town'] == '中正區'
        assert result['temperature_c'] == 27.5
    asyncio.run(scenario())


def forecast_facts(days=7):
    start = datetime(2026, 10, 29, tzinfo=TAIPEI)
    values = {'temperature_c': 25, 'max_temperature_c': 28, 'min_temperature_c': 22,
              'max_apparent_temperature_c': 29, 'min_apparent_temperature_c': 21,
              'precipitation_probability_12h': None, 'weather': '多雲短暫陣雨'}
    series = {name: [] for name in values}
    for index in range(days * 2):
        begin = start + timedelta(hours=index * 12)
        end = begin + timedelta(hours=12)
        for name, value in values.items():
            if name.startswith('precipitation') and index >= 6:
                continue
            series[name].append(dict(start=begin.isoformat(), end=end.isoformat(), value=value))
    return dict(status='available', source=SOURCE, source_url=SOURCE_URL, county='臺北市', town='',
        kind='forecast', fetched_at=start.isoformat(), issued_at=None, timezone='Asia/Taipei',
        start_date=start.date().isoformat(), end_date=(start + timedelta(days=days - 1)).date().isoformat(),
        series=series, probability_note='一週產品的降雨機率僅前三天提供；未提供不代表 0%。')


def points(series):
    return Counter(json.dumps([name, item['start'], item['end'], item['value']], ensure_ascii=False)
                   for name, items in series.items() for item in items)


@pytest.mark.parametrize('extra', ['none', 'conflict', 'different_interval'])
def test_forecast_transport_preserves_every_interval_value_and_source(extra):
    original = forecast_facts()
    if extra == 'conflict':
        original['series']['temperature_c'].append({**original['series']['temperature_c'][0], 'value': 26})
    if extra == 'different_interval':
        original['series']['temperature_c'][0]['end'] = None
    before = deepcopy(original)
    payload = json.loads(weather_prompt(original).split('\n')[-1])
    restored = {}
    for row in payload['forecast_periods']:
        for name, value in row.items():
            if name not in {'start', 'end'}:
                restored.setdefault(name, []).append(dict(start=row['start'], end=row['end'], value=value))
    assert points(restored) == points(original['series'])
    assert {k: v for k, v in payload.items() if k != 'forecast_periods'} == {
        k: v for k, v in original.items() if k != 'series'}
    assert original == before
    assert all('precipitation_probability_12h' not in row
               for row in payload['forecast_periods'] if row['start'][:10] >= '2026-11-01')


def test_observation_and_failure_facts_remain_unchanged():
    for result in [dict(status='available', kind='current', station='臺北', temperature_c=25,
                        observed_at='2026-10-29T12:00:00+08:00', humidity_percent=None),
                   dict(status='unavailable', source=SOURCE)]:
        assert json.loads(weather_prompt(result).split('\n')[-1]) == result


def test_today_then_week_fits_without_discarding_history_or_displayed_board(monkeypatch):
    from nova_llm import context_usage
    config = Config()
    config.llm.provider = 'llamacpp'
    config.llm.assistant_profile.assistant_name = '天氣助手'
    config.llm.assistant_profile.system_prompt = '依本輪氣象資料回答，說明地點與適用時段。'
    llm = OpenAILLM(config=config, api_key='test', base_url='http://weather-context-test/v1')
    # The local estimate counts each CJK character as a token, an upper bound
    # for the deployed tokenizer; the separate live probe measures Qwen's.
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'default_generation_settings': {'n_ctx': 8192}}
    monkeypatch.setattr(context_usage.requests, 'get', lambda *_, **__: Response())
    assert context_usage.deployed_capacity(llm.base_url, refresh=True) == 8192
    llm._client = Mock()
    llm._client.chat.completions.create.side_effect = lambda **_: [SimpleNamespace(choices=[
        SimpleNamespace(delta=SimpleNamespace(content='[[MODE:SIMPLE]]\n[[SPEECH]]\n臺北市今天多雲，請留意降雨並攜帶雨具。\n[[END]]'))])]
    info = {'on_mode': lambda *_: None}
    llm.generate_response('今天台北天氣如何？',
        datainfo=info, rag_context=weather_prompt(forecast_facts(1)))
    board = SessionBoardContext(turn_id='today', title='臺北市今天天氣', summary=None,
        items=[BoardItem(title='上午', content='多雲，22–28°C；降雨機率未提供。'),
               BoardItem(title='下午', content='短暫陣雨，請留意天氣變化。')])
    llm.set_last_board(board)
    history = deepcopy(llm.conversation_history)
    llm.generate_response('未來一週天氣如何？',
        datainfo=info, rag_context=weather_prompt(forecast_facts()))
    assert llm.context_usage['over_capacity'] is False
    assert llm.context_usage['input_tokens'] + llm.context_usage['reserved_output_tokens'] <= 8192
    assert llm.conversation_history[:2] == history
    assert len(llm.conversation_history) == 4
    assert llm.get_last_board() is board
    assert llm._client.chat.completions.create.call_count == 2
