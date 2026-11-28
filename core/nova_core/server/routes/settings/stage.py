# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""設定 API：舞台設定與舞台背景。"""
from __future__ import annotations

import asyncio
import json
from uuid import uuid4
from aiohttp import web
from nova_contracts.common import ServiceError
from nova_core.server.runtime_settings import (
    SettingsError,
    apply_stage_settings,
    apply_stage_background,
    stage_snapshot,
)
from nova_core.server.state import state
from nova_core.utils.logging import logger
from nova_core.server.routes.settings.shared import _json


async def get_stage_settings(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    return _json({"code": 0, "data": stage_snapshot(state.config),
                  "greetings": [{"sessionid": v.sessionid, "status": v.greetings.status,
                                 "error": v.greetings.error}
                                for v in state.voice_sessions.values()
                                if v._presenter == "stage"]})


async def set_stage_settings(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        params = await request.json()
        from copy import deepcopy
        roles = getattr(state, "roles", None)
        if params.get("idle_greeting_enabled") is True and roles is not None and not roles.profiles_applied:
            raise SettingsError("請先將主數位人設定儲存並套用，再啟用閒置招呼")
        main = roles.profiles[roles.current_id] if roles is not None else None
        result = apply_stage_settings(state.config, params, greeting_content=main.get("greeting") if main else None)
        for voice in state.voice_sessions.values():
            voice.config.stage = deepcopy(state.config.stage)
            voice._cancel_idle_reset()
            voice.greetings.refresh()
            voice._refresh_gate()
        if roles is not None:
            roles.notify()
        if not result['composer_enabled']:
            for session in list(state.voice_sessions.values()):
                if session._presenter == 'stage':
                    session.attachments.clear(drafts_only=True)
                    session._composer_editing = False
                    session._emit('composer_disabled')
                    session._refresh_gate()
        return _json({"code": 0, "msg": "ok", "data": result})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        logger.exception("更新舞台設定失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def get_backgrounds(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    return _json({"code": 0, "data": {
        "items": state.avatar_service.list_backgrounds(),
        **state.avatar_service.scene_snapshot(),
    }})


async def upload_background(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    avatars = state.avatar_service
    root = avatars.backgrounds_root()
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / f".upload-{uuid4().hex}"
    try:
        reader = await request.multipart()
        part = await reader.next()
        if part is None or part.name != "background" or not part.filename:
            return _json({"code": -1, "msg": "請選擇背景圖片、GIF 或影片"}, status=400)
        original_name = part.filename
        size = 0
        with temporary.open("wb") as handle:
            while True:
                chunk = await part.read_chunk(size=1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > avatars.max_background_bytes:
                    return _json({"code": -1, "msg": "背景檔案不可超過 100 MB"}, status=413)
                handle.write(chunk)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, avatars.add_background, temporary, original_name)
        return _json({"code": 0, "msg": "ok", "data": result})
    except ServiceError as exc:
        return _json({"code": -1, "msg": str(exc)}, status=400)
    except Exception as exc:
        logger.exception("上傳舞台背景失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)
    finally:
        temporary.unlink(missing_ok=True)


async def select_background(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        params = await request.json()
        if not isinstance(params, dict):
            raise SettingsError("背景設定格式不正確", status=400)
        result = await asyncio.to_thread(
            apply_stage_background,
            state.config,
            params.get("background_id", ""),
            avatars=state.avatar_service,
        )
        return _json({"code": 0, "msg": "ok", "data": result})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        logger.exception("切換舞台背景失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def background_preview(request):
    try:
        return web.FileResponse(
            state.avatar_service.background_preview(request.match_info["background_id"]))
    except ServiceError:
        raise web.HTTPNotFound()


async def delete_background(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    background_id = request.match_info.get("background_id", "")
    if background_id in {
        state.avatar_service.scene_snapshot()["background_id"],
        str(getattr(state.config.stage, "background_id", "") or ""),
    }:
        return _json({"code": -1, "msg": "正在使用的背景無法刪除，請先切換背景"}, status=409)
    try:
        archived = state.avatar_service.archive_background(background_id)
        return _json({"code": 0, "msg": "ok", "data": {
            "background_id": background_id, "archived_as": archived,
        }})
    except ServiceError as exc:
        return _json({"code": -1, "msg": str(exc)}, status=404)
    except Exception as exc:
        logger.exception("刪除舞台背景失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def archived_backgrounds(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    return _json({"code": 0, "data": {"items": state.avatar_service.list_archived_backgrounds()}})


async def restore_archived_background(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        background_id = state.avatar_service.restore_background(
            request.match_info.get("archive_name", ""))
        return _json({"code": 0, "msg": "ok", "data": {"background_id": background_id}})
    except ServiceError as exc:
        return _json({"code": -1, "msg": str(exc)}, status=409)
    except Exception as exc:
        logger.exception("復原舞台背景失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)
