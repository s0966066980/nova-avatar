# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Matcha-TTS 控制台引導式語音訓練 HTTP API 路由。"""

from __future__ import annotations

import json

from aiohttp import web

from src.server.runtime_settings import SettingsError
from src.server.state import state
from src.server.tts_training_jobs import (
    ALL_STEPS,
    cancel_training_job,
    get_training_snapshot,
    parse_training_config,
    start_training_step,
    synthesize_edge_voice_preview,
)


def _json(payload: dict, status: int = 200) -> web.Response:
    return web.Response(
        status=status,
        content_type="application/json",
        text=json.dumps(payload, ensure_ascii=False),
    )


def _active_session_count() -> int:
    return sum(1 for stream in state.avatar_streams.values() if stream is not None)


async def get_tts_training_status(request: web.Request) -> web.Response:
    slug = (request.query.get("slug") or "zh-tw-custom").strip()
    try:
        data = get_training_snapshot(slug=slug)
        data["session_count"] = _active_session_count()
        return _json({"code": 0, "data": data})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def run_tts_training_step(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return _json({"code": -1, "msg": "請求格式必須為 JSON"}, status=400)
    if not isinstance(payload, dict):
        return _json({"code": -1, "msg": "請求格式必須為物件"}, status=400)

    step = str(payload.get("step") or "").strip().lower()
    if step not in ALL_STEPS:
        return _json({"code": -1, "msg": f"不支援的訓練步驟：{step or '(空值)'}"}, status=400)

    try:
        cfg = parse_training_config(payload)
        job = start_training_step(
            step=step,
            cfg=cfg,
            session_count=_active_session_count(),
        )
        return _json({"code": 0, "msg": "ok", "data": job.to_dict()})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def cancel_tts_training(request: web.Request) -> web.Response:
    del request
    data = cancel_training_job()
    return _json({"code": 0, "msg": "ok", "data": data})


async def preview_tts_teacher_voice(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return _json({"code": -1, "msg": "請求格式必須為 JSON"}, status=400)
    if not isinstance(payload, dict):
        return _json({"code": -1, "msg": "請求格式必須為物件"}, status=400)

    voice = str(payload.get("voice") or "").strip()
    text = str(payload.get("text") or "").strip() or None
    try:
        preview_audio = await synthesize_edge_voice_preview(voice, text)
        return _json(
            {
                "code": 0,
                "msg": "ok",
                "data": {"voice": voice, "preview_audio": preview_audio},
            }
        )
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        return _json({"code": -1, "msg": str(exc)}, status=500)
