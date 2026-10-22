# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Role library and directed transitions; credentials never enter these payloads."""
import asyncio
from functools import wraps
from pathlib import Path
import tempfile

from aiohttp import web
from src.profiles.media import MAX_BYTES
from src.profiles.store import ProfileError, validate_profile, profile_config
from src.greetings.content import prepare_greeting, GreetingError
from src.server.state import state


def endpoint(handler):
    @wraps(handler)
    async def wrapped(request):
        try:
            roles = getattr(state, "roles", None)
            if roles is None:
                raise ProfileError("角色設定服務尚未初始化", 503)
            return await handler(request, roles)
        except ProfileError as exc:
            return web.json_response({"code": -1, "msg": str(exc)}, status=exc.status)
        except (ValueError, TypeError, KeyError):
            return web.json_response({"code": -1, "msg": "角色設定格式不正確"}, status=400)
    return wrapped


@endpoint
async def library(request, roles):
    return web.json_response({"code": 0, "library": roles.store.load(),
                              "runtime": roles.snapshot(), "media": roles.media.list(),
                              "greeting_profile": roles.profiles[roles.library["pair"]["main"]]})


@endpoint
async def save(request, roles):
    body = await request.json()
    value = body["library"]
    # Applied profiles must remain addressable until a different pair is applied.
    if roles.enabled:
        ids = {p["id"] for p in value["profiles"]}
        if not set(roles.library["pair"].values()) <= ids:
            raise ProfileError("請先套用其他角色組合，再刪除使用中的設定檔", 409)
    saved = roles.store.save(value, expected_revision=body["expected_revision"])
    return web.json_response({"code": 0, "library": saved, "runtime": roles.snapshot()})


@endpoint
async def apply(request, roles):
    return web.json_response({"code": 0, "runtime": await roles.apply()})


@endpoint
async def mode(request, roles):
    return web.json_response({"code": 0, "runtime": await roles.set_mode((await request.json())["mode"])})


@endpoint
async def return_main(request, roles):
    requester = next(iter(state.voice_sessions.values()), None)
    if requester is None:
        raise ProfileError("請先連線數位人", 409)
    return web.json_response({"code": 0, "runtime": await roles.return_to_main(requester)})


@endpoint
async def stop(request, roles):
    for voice in list(state.voice_sessions.values()):
        if not voice._is_conversation_idle():
            await voice.interrupt()
    return web.json_response({"code": 0, "runtime": roles.snapshot()})


@endpoint
async def upload(request, roles):
    reader = await request.multipart()
    part = await reader.next()
    if part is None or not part.filename:
        raise ProfileError("請選擇轉場影片")
    filename = part.filename
    with tempfile.TemporaryDirectory(prefix="nova-transition-") as directory:
        path = Path(directory) / "upload"
        total = 0
        with path.open("wb") as handle:
            while chunk := await part.read_chunk(64 * 1024):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise ProfileError("影片不可超過 100 MiB", 413)
                handle.write(chunk)
        importing = asyncio.create_task(asyncio.to_thread(roles.media.import_file, path, filename))
        try:
            info = await asyncio.shield(importing)
        except asyncio.CancelledError:
            # Keep the source alive until the worker finishes, then remove the
            # newly created, unpublished asset owned by this cancelled upload.
            try:
                orphan = await importing
                roles.media.delete(orphan["id"], referenced=set())
            except ProfileError:
                pass
            raise
    return web.json_response({"code": 0, "asset": info, "media": roles.media.list()})


@endpoint
async def preview(request, roles):
    _, path = roles.media.get(request.match_info["asset_id"])
    return web.FileResponse(path, headers={"Content-Type": "video/mp4"})


@endpoint
async def delete_media(request, roles):
    referenced = {e.get("asset_id") for lib in (roles.store.load(), roles.library)
                  for e in lib["transitions"] if e["kind"] == "video"}
    roles.media.delete(request.match_info["asset_id"], referenced=referenced)
    return web.json_response({"code": 0, "media": roles.media.list()})


@endpoint
async def apply_greeting(request, roles):
    body = await request.json()
    runtime = await roles.apply_greeting(body["profile_id"], expected_revision=body["expected_revision"])
    return web.json_response({"code": 0, "runtime": runtime})


@endpoint
async def greeting_preview(request, roles):
    body = await request.json()
    try:
        config = profile_config(state.config, validate_profile(body["profile"]))
        result = await prepare_greeting(config)
    except GreetingError as exc:
        raise ProfileError(str(exc)) from exc
    return web.json_response({"code": 0, **result})


@endpoint
async def greeting_try(request, roles):
    body = await request.json()
    voice = state.voice_sessions.get(int(body.get("sessionid", 0)))
    if roles.mode != "console" or voice is None or voice._presenter != "console" or not voice.event_sink_ready:
        raise ProfileError("請切換到控制台測試模式並建立播放連線", 409)
    config = profile_config(state.config, validate_profile(body["profile"]))
    if config.tts.type != voice.config.tts.type:
        raise ProfileError("請先載入草稿使用的語音引擎，再執行試播", 409)
    if not voice._is_conversation_idle() or voice._greeting_trial_preparation is not None:
        raise ProfileError("請等待目前對話或試播結束", 409)
    # Keep this request cancellable and recheck ownership after AI preparation.
    generation = voice._generation
    preparing = asyncio.create_task(prepare_greeting(config, previous=voice.greetings.previous))
    voice._greeting_trial_preparation = preparing
    try:
        result = await preparing
        still_owned = voice._greeting_trial_preparation is preparing
    except asyncio.CancelledError as exc:
        raise ProfileError("試播已取消，請重新預覽或試播", 409) from exc
    except GreetingError as exc:
        raise ProfileError(str(exc)) from exc
    finally:
        if voice._greeting_trial_preparation is preparing:
            voice._greeting_trial_preparation = None
    if not still_owned or roles.mode != "console" or voice._closed or voice._generation != generation or not voice._is_conversation_idle():
        raise ProfileError("試播準備期間連線或對話狀態已改變，請再試一次", 409)
    try:
        turn_id = voice.start_greeting(result["text"], playback_config=config)
    except GreetingError as exc:
        raise ProfileError(str(exc)) from exc
    return web.json_response({"code": 0, **result, "turn_id": turn_id}, status=202)


def register_profile_routes(app):
    app.router.add_post("/api/profiles/greeting/apply", apply_greeting)
    app.router.add_post("/api/profiles/greeting/preview", greeting_preview)
    app.router.add_post("/api/profiles/greeting/try", greeting_try)
    app.router.add_get("/api/profiles", library)
    app.router.add_put("/api/profiles", save)
    app.router.add_post("/api/profiles/apply", apply)
    app.router.add_post("/api/profiles/mode", mode)
    app.router.add_post("/api/profiles/return", return_main)
    app.router.add_post("/api/profiles/stop", stop)
    app.router.add_post("/api/profiles/media", upload)
    app.router.add_get("/api/profiles/media/{asset_id}", preview)
    app.router.add_delete("/api/profiles/media/{asset_id}", delete_media)
