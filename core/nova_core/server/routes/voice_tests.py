# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Console endpoints for running and reviewing real voice pipeline tests."""
from __future__ import annotations

from typing import Any

from aiohttp import web

from src.server.state import state


def _json(payload: dict[str, Any], *, status: int = 200) -> web.Response:
    return web.json_response(payload, status=status)


def _setting_value(container: Any, name: str, default: str = "") -> str:
    return str(getattr(container, name, default) or default)


def _environment_snapshot(reply_mode: str) -> dict[str, str]:
    config = state.config
    model = getattr(config, "model", None)
    llm = getattr(config, "llm", None)
    asr = getattr(config, "asr", None)
    tts = getattr(config, "tts", None)
    return {
        "llm": _setting_value(llm, "provider"),
        "llm_model": _setting_value(llm, "model"),
        "avatar": _setting_value(model, "type"),
        "avatar_id": _setting_value(model, "avatar_id"),
        "asr": _setting_value(asr, "type"),
        "tts": _setting_value(tts, "type"),
        "reply_mode": str(reply_mode or ""),
    }


async def list_voice_tests(request: web.Request) -> web.Response:
    try:
        limit = int(request.query.get("limit", 50))
    except ValueError:
        raise web.HTTPBadRequest(text="limit 必須是整數")
    return _json({"code": 0, "results": state.voice_test_history.list(limit=limit)})


async def run_voice_test(request: web.Request) -> web.Response:
    try:
        params = await request.json()
    except (ValueError, TypeError):
        raise web.HTTPBadRequest(text="請提供有效的 JSON")

    try:
        session_id = int(params.get("sessionid", 0))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text="sessionid 必須是整數")
    prompt = str(params.get("prompt") or "").strip()
    label = str(params.get("label") or "").strip()
    if not prompt:
        raise web.HTTPBadRequest(text="測試 prompt 不可為空")
    if len(prompt) > 2000:
        raise web.HTTPBadRequest(text="測試 prompt 不可超過 2000 字")
    if len(label) > 80:
        raise web.HTTPBadRequest(text="測試名稱不可超過 80 字")

    voice_session = state.voice_sessions.get(session_id)
    avatar_stream = state.avatar_streams.get(session_id)
    if voice_session is None or avatar_stream is None:
        raise web.HTTPConflict(text="請先建立 WebRTC 語音連線")
    if not getattr(voice_session, "event_sink_ready", False):
        raise web.HTTPConflict(text="回覆事件通道尚未就緒，請稍後再試")
    try:
        started = await voice_session.start_text_turn(prompt, interrupt=False)
    except (RuntimeError, ValueError) as exc:
        raise web.HTTPConflict(text=str(exc))

    record = state.voice_test_history.begin(
        turn_id=started["turn_id"],
        prompt=prompt,
        session_id=session_id,
        environment=_environment_snapshot(started.get("reply_mode", "")),
        label=label,
    )
    return _json(
        {
            "code": 0,
            "msg": "accepted",
            "record": record,
            **started,
        },
        status=202,
    )


async def clear_voice_tests(_request: web.Request) -> web.Response:
    if state.voice_test_history.has_running:
        raise web.HTTPConflict(text="測試執行中，請等待完成後再清除紀錄")
    count = state.voice_test_history.clear()
    return _json({"code": 0, "msg": "測試紀錄已清除", "cleared": count})
