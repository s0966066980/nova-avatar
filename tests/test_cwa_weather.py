# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Contract fixtures based on CWA's documented fields, not a live-key acceptance."""
import asyncio
from datetime import datetime, timedelta

from src.profiles.weather import (
    CwaWeather, TAIPEI, WeatherQuery, WeatherUnavailable,
    normalize_forecast, normalize_observation, weather_prompt,
)

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


def test_missing_key_and_out_of_range_fail_before_network(monkeypatch):
    monkeypatch.setattr("src.profiles.weather.cwa_key", lambda: "")
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
