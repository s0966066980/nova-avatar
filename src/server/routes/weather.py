# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Console API for Central Weather Administration (CWA) weather tool settings and testing."""
from __future__ import annotations

import asyncio
import json

from aiohttp import web

from src.config.overrides import persist_runtime_overrides
from src.config.schema import WeatherConfig
from src.server.state import state
from src.weather import (
    COUNTIES,
    SOURCE,
    SOURCE_URL,
    WeatherQuery,
    canonical_county,
    resolve_weather_plan,
    weather_reply,
    weather_service,
)


def _json(data: dict, status: int = 200) -> web.Response:
    return web.Response(
        status=status,
        content_type="application/json",
        text=json.dumps(data, ensure_ascii=False),
    )


def weather_snapshot(config) -> dict:
    weather_cfg = getattr(config, "weather", None)
    return {
        "enabled": bool(getattr(weather_cfg, "enabled", True)) if weather_cfg is not None else True,
        "county": str(getattr(weather_cfg, "county", "") or ""),
        "town": str(getattr(weather_cfg, "town", "") or ""),
        "configured": bool(weather_service.configured),
        "counties": list(COUNTIES),
        "source": SOURCE,
        "source_url": SOURCE_URL,
    }


def validate_weather_settings(payload: object, current: WeatherConfig) -> WeatherConfig:
    if not isinstance(payload, dict):
        raise ValueError("天氣設定內容必須是物件")
    enabled = payload.get("enabled", current.enabled)
    if not isinstance(enabled, bool):
        raise ValueError("啟用狀態必須是布林值")
    raw_county = payload.get("county", current.county)
    if not isinstance(raw_county, str):
        raise ValueError("預設縣市必須是字串")
    county = raw_county.strip().replace("台", "臺")
    if county:
        county = canonical_county(county) or county
        if county not in COUNTIES:
            raise ValueError("預設縣市必須是臺灣 22 個縣市之一或留空")
    raw_town = payload.get("town", current.town)
    if not isinstance(raw_town, str):
        raise ValueError("預設鄉鎮市區必須是字串")
    town = raw_town.strip().replace("台", "臺")
    if len(town) > 40:
        raise ValueError("預設鄉鎮市區不可超過 40 字")
    if not county:
        town = ""
    return WeatherConfig(enabled=enabled, county=county, town=town)


async def get_weather_settings(request) -> web.Response:
    return _json({"code": 0, "data": weather_snapshot(state.config)})


async def put_weather_settings(request) -> web.Response:
    try:
        payload = await request.json()
        current = getattr(state.config, "weather", None) or WeatherConfig()
        next_weather = validate_weather_settings(payload, current)
    except (ValueError, json.JSONDecodeError) as exc:
        return _json({"code": -1, "msg": str(exc)}, status=400)
    previous = getattr(state.config, "weather", None)
    state.config.weather = next_weather
    try:
        persist_runtime_overrides(state.config)
    except Exception as exc:
        state.config.weather = previous
        return _json({"code": -1, "msg": f"儲存天氣設定失敗：{exc}"}, status=500)
    return _json({"code": 0, "data": weather_snapshot(state.config)})


async def test_weather_query(request) -> web.Response:
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("測試內容必須是物件")
        question = str(payload.get("question") or "").strip()
        if not question or len(question) > 500:
            raise ValueError("測試問題須為 1 至 500 字")
    except (ValueError, json.JSONDecodeError) as exc:
        return _json({"code": -1, "msg": str(exc)}, status=400)

    plan = await asyncio.to_thread(
        resolve_weather_plan,
        state.config,
        question,
        [],
        {},
    )
    if plan.get("route") == "specialist":
        result = await weather_service.query(
            WeatherQuery(
                county=str(plan.get("county") or ""),
                town=str(plan.get("town") or ""),
                kind=str(plan.get("kind") or "forecast"),
                start_date=str(plan.get("start_date") or ""),
                end_date=str(plan.get("end_date") or ""),
            )
        )
        speech_summary, board_summary = weather_reply(result)
        return _json({
            "code": 0,
            "data": {
                "route": "specialist",
                "plan": plan,
                "result": result,
                "summary": speech_summary,
                "board": board_summary,
            },
        })
    if plan.get("route") == "clarify":
        return _json({
            "code": 0,
            "data": {
                "route": "clarify",
                "plan": plan,
                "result": None,
                "summary": str(plan.get("clarification") or ""),
            },
        })
    return _json({
        "code": 0,
        "data": {
            "route": str(plan.get("route") or "answer"),
            "plan": plan,
            "result": None,
            "summary": "此問題未觸發天氣查詢工具（或已停用即時氣象查詢）。",
        },
    })
