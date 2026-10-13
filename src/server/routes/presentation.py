# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Presentation controls, safe media serving, and asynchronous production."""
import asyncio
from copy import deepcopy
from functools import wraps
from pathlib import Path
import uuid

from aiohttp import web
from src.avatars import presentation as assets
from src.server import presentation_jobs as jobs
from src.server.state import state
from src.server.runtime_settings import SettingsError


def endpoint(handler):
    @wraps(handler)
    async def wrapped(request):
        try:
            return await handler(request)
        except SettingsError as exc:
            return web.json_response({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
        except (assets.PresentationError, ValueError, KeyError) as exc:
            return web.json_response({"code": -1, "msg": str(exc)}, status=400)
        except Exception as exc:
            from src.utils.logging import logger
            logger.exception("Presentation request failed")
            return web.json_response({"code": -1, "msg": str(exc)}, status=500)
    return wrapped


def disconnected():
    if state.avatar_streams or state.pcs or state.switching:
        raise SettingsError("請先斷開控制台與舞台；製作期間也不能變更設定", status=409)


@endpoint
async def get_presentation(request):
    value = assets.snapshot(state.config, request.match_info["avatar_id"])
    value.update(active_sessions=len(state.avatar_streams), busy=bool(state.switching))
    return web.json_response({"code": 0, "data": value})


@endpoint
async def set_presentation(request):
    from src.server.runtime_settings import _SWITCH_LOCK, _reload_avatar
    from src.config.overrides import persist_runtime_overrides
    avatar_id = request.match_info["avatar_id"]
    params = await request.json()
    assets.folder(avatar_id)
    action = params.get("action", "mode")
    if action == "mode":
        selected = params.get("mode")
        if selected not in {"musetalk", "prerecorded"}:
            raise assets.PresentationError("無效的呈現方式")
        if selected == "prerecorded" and not assets.snapshot(state.config, avatar_id)["ready"]:
            raise assets.PresentationError(assets.snapshot(state.config, avatar_id)["reason"])
        if not state.switching and selected == assets.mode(state.config, avatar_id):
            return await get_presentation(request)
    elif action not in {"apply", "restore"}:
        raise assets.PresentationError("無效的操作")
    if not _SWITCH_LOCK.acquire(blocking=False):
        raise SettingsError("正在切換或製作數位人", status=409)
    try:
        if params.get("reconnect") is True:
            if state.switching or any(value is None for value in state.avatar_streams.values()):
                raise SettingsError("正在準備連線或製作數位人，請稍候再切換", status=409)
            state.switching = True
            from src.server.routes.webrtc import close_sessions
            await close_sessions(presentation_change=True)
        else:
            disconnected()
            state.switching = True

        def apply():
            # RLock must be acquired and released by the same worker thread.
            # Loading GPU models here keeps HTTP/health/connection polling alive.
            with assets.LOCK:
                previous = deepcopy(state.config.model.presentation_modes)
                previous_assets = None
                try:
                    if action in {"apply", "restore"}:
                        previous_assets = assets.read(avatar_id)
                        assets.apply_asset(avatar_id, params.get("slot"), restore=action == "restore")
                    else:
                        state.config.model.presentation_modes[avatar_id] = selected
                    active = avatar_id == state.config.model.avatar_id
                    should_reload = active and (action == "mode" or assets.mode(state.config) == "prerecorded")
                    if should_reload and (assets.mode(state.config) != "prerecorded" or assets.snapshot(state.config)["ready"]):
                        _reload_avatar(state.config, state.config.model.type, avatar_id)
                    else:
                        persist_runtime_overrides(state.config)
                except Exception:
                    state.config.model.presentation_modes = previous
                    if previous_assets is not None:
                        assets._save(avatar_id, previous_assets)
                    raise
        pending = asyncio.create_task(asyncio.to_thread(apply))
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError:
            # Disconnecting the browser does not release the workspace while
            # its model-loading thread is still mutating it.
            await pending
            raise
    finally:
        state.switching = False
        _SWITCH_LOCK.release()
    return await get_presentation(request)


async def upload(request, max_bytes):
    reader = await request.multipart()
    part = await reader.next()
    if not part or not part.filename:
        raise assets.PresentationError("請選擇影片")
    destination = jobs.root() / f"{uuid.uuid4().hex}.upload"
    size = 0
    try:
        with destination.open("wb") as output:
            while chunk := await part.read_chunk(256 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise assets.PresentationError(f"影片超過 {max_bytes // 1024**2} MB 上限")
                output.write(chunk)
        if not size:
            raise assets.PresentationError("影片是空檔案")
        return destination, Path(part.filename).suffix.lower()
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


@endpoint
async def upload_asset(request):
    avatar_id, slot = request.match_info["avatar_id"], request.match_info["slot"]
    assets.folder(avatar_id)
    if slot not in assets.SLOTS:
        raise assets.PresentationError("無效的素材類型")
    source, suffix = await upload(request, 100 * 1024**2)
    if suffix != ".mp4":
        source.unlink(missing_ok=True)
        raise assets.PresentationError("第一版請上傳 MP4")
    value = jobs.submit("upload", config=state.config, avatar_id=avatar_id, slot=slot, source=source)
    return web.json_response({"code": 0, "data": value})


@endpoint
async def generate_asset(request):
    disconnected()
    avatar_id = request.match_info["avatar_id"]
    if state.config.model.avatar_id != avatar_id or state.config.model.type != "musetalk":
        raise assets.PresentationError("請先套用具有 MuseTalk 素材的角色，再製作說話影片")
    if not (assets.folder(avatar_id).parent / "avator_info.json").is_file():
        raise assets.PresentationError("缺少角色來源資訊")
    from src.avatars.catalog import avatar_uses_green_screen
    if not avatar_uses_green_screen(avatar_id):
        raise assets.PresentationError("說話素材製作需要綠幕角色")
    params = await request.json()
    text = str(params.get("text", "")).strip()
    if not text or len(text) > 1000:
        raise assets.PresentationError("請輸入 1 至 1000 字的朗讀文字")
    value = jobs.submit("generate", config=state.config, avatar_id=avatar_id, text=text)
    return web.json_response({"code": 0, "data": value})


@endpoint
async def job_status(request):
    return web.json_response({"code": 0, "data": jobs.status(request.match_info["job_id"])})


@endpoint
async def cancel_job(request):
    return web.json_response({"code": 0, "data": jobs.cancel(request.match_info["job_id"])})


@endpoint
async def media(request):
    return web.FileResponse(assets.media_path(request.match_info["avatar_id"], request.match_info["name"]))


@endpoint
async def background_media(request):
    from src.scene.service import _asset_paths
    path = _asset_paths(request.match_info["background_id"])[0]
    if path.suffix.lower() == ".gif":
        import asyncio
        def convert():
            with assets.LOCK:
                target = path.with_name(f"{path.stem}.browser.mp4")
                if not target.exists():
                    temporary = target.with_name(f".{uuid.uuid4().hex}.mp4")
                    try:
                        assets.normalize(path, temporary)
                        temporary.replace(target)
                    finally:
                        temporary.unlink(missing_ok=True)
                return target
        path = await asyncio.to_thread(convert)
    return web.FileResponse(path)


@endpoint
async def export_record(request):
    source, suffix = await upload(request, 512 * 1024**2)
    value = jobs.submit("record", config=state.config, source=source, source_suffix=suffix)
    return web.json_response({"code": 0, "data": value})


def register(app):
    app.router.add_get("/api/presentation/jobs/{job_id}", job_status)
    app.router.add_post("/api/presentation/jobs/{job_id}/cancel", cancel_job)
    app.router.add_post("/api/presentation/records", export_record)
    app.router.add_get("/api/presentation/background/{background_id}", background_media)
    app.router.add_get("/api/presentation/{avatar_id}", get_presentation)
    app.router.add_post("/api/presentation/{avatar_id}", set_presentation)
    app.router.add_post("/api/presentation/{avatar_id}/upload/{slot}", upload_asset)
    app.router.add_post("/api/presentation/{avatar_id}/generate", generate_asset)
    app.router.add_get("/api/presentation/{avatar_id}/media/{name}", media)
