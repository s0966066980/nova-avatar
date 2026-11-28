# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""設定 API：數位人、嘴型畫質、輸出尺寸與角色匯入。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4
from aiohttp import web
from nova_contracts.common import ServiceError
from nova_core.server.import_jobs import (
    MAX_IMPORT_VIDEO_BYTES,
    VIDEO_EXTS,
    discard_upload,
    get_job,
    import_in_progress,
    start_import_job,
    validate_import_request,
)
from nova_core.server.runtime_settings import (
    apply_video_settings,
    SettingsError,
    apply_avatar,
    apply_mouth_quality,
    current_snapshot,
)
from nova_core.profiles.store import ProfileError
from nova_core.server.deferred_settings import defer_when_connected
from nova_core.server.state import state
from nova_core.utils.logging import logger
from nova_core.server.routes.settings.shared import _json, _active_session_count


@defer_when_connected("數位人引擎", lambda config: current_snapshot(config, tts=state.tts, avatars=state.avatar_service)["avatar"])
async def set_avatar(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        params = await request.json()
        result = apply_avatar(
            state.config,
            params.get("type", ""),
            params.get("avatar_id", ""),
            session_count=_active_session_count(),
            avatars=state.avatar_service,
        )
        return _json({"code": 0, "msg": "ok", "data": result})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        logger.exception("切換數字人失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def set_video_output(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        result = apply_video_settings(state.config, await request.json(), avatars=state.avatar_service)
        result["requires_reconnect"] = bool(_active_session_count())
        return _json({"code": 0, "msg": "ok", "data": result})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message}, status=exc.status)
    except Exception as exc:
        logger.exception("更新數字人輸出解析度失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def set_mouth_quality(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        params = await request.json()
        result = apply_mouth_quality(state.config, params or {}, avatars=state.avatar_service)
        return _json({"code": 0, "msg": "ok", "data": result})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        logger.exception("套用嘴型畫質失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def avatar_preview(request):
    avatar_id = request.match_info.get("avatar_id", "")
    preview = state.avatar_service.preview_image(avatar_id)
    if preview is None or not preview.is_file():
        return _json({"code": -1, "msg": "預覽圖不存在"}, status=404)
    return web.FileResponse(preview)


async def avatar_scene_preview(request):
    avatar_id = request.match_info.get("avatar_id", "")
    try:
        loop = asyncio.get_running_loop()
        image = await loop.run_in_executor(None, state.avatar_service.render_avatar_preview, avatar_id)
        return web.Response(body=image, content_type="image/jpeg", headers={"Cache-Control": "no-store"})
    except ServiceError:
        raise web.HTTPNotFound()


async def delete_avatar(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    avatar_id = request.match_info.get("avatar_id", "")
    roles = getattr(state, "roles", None)
    if roles and any(p["avatar_id"] == avatar_id for lib in (roles.library, roles.store.load()) for p in lib["profiles"]):
        return _json({"code": -1, "msg": "請先解除角色設定檔對此人物素材的引用"}, status=409)
    if avatar_id == state.config.model.avatar_id:
        return _json({"code": -1, "msg": "正在使用的數字人無法刪除，請先切換角色"}, status=409)
    if _active_session_count():
        return _json({"code": -1, "msg": "請先結束連線再刪除數字人"}, status=409)
    if import_in_progress():
        return _json({"code": -1, "msg": "數字人正在製作，請稍後再刪除"}, status=409)
    try:
        archived = state.avatar_service.archive_avatar(avatar_id)
        return _json({"code": 0, "msg": "ok", "data": {
            "avatar_id": avatar_id, "archived_as": archived,
        }})
    except ServiceError as exc:
        return _json({"code": -1, "msg": str(exc)}, status=404)
    except Exception as exc:
        logger.exception("刪除數字人失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def archived_avatars(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    return _json({"code": 0, "data": {"items": state.avatar_service.list_archived_avatars()}})


async def restore_archived_avatar(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    if import_in_progress():
        return _json({"code": -1, "msg": "數字人正在製作，請稍後再復原"}, status=409)
    try:
        avatar_id = state.avatar_service.restore_avatar(request.match_info.get("archive_name", ""))
        return _json({"code": 0, "msg": "ok", "data": {"avatar_id": avatar_id}})
    except ServiceError as exc:
        return _json({"code": -1, "msg": str(exc)}, status=409)
    except Exception as exc:
        logger.exception("復原數字人失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def delete_archived_avatar_permanently(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        avatar_id = state.avatar_service.delete_archived_avatar(request.match_info.get("archive_name", ""))
        return _json({"code": 0, "msg": "ok", "data": {"avatar_id": avatar_id}})
    except ServiceError as exc:
        return _json({"code": -1, "msg": str(exc)}, status=404)
    except Exception as exc:
        logger.exception("永久刪除封存數字人失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


def _avatar_replace_conflict(avatar_id: str) -> str | None:
    """Why an existing avatar must not be replaced by an import, or None."""
    config = state.config
    if config is not None and avatar_id == config.model.avatar_id:
        return "正在使用的數字人無法覆寫，請先切換角色"
    roles = getattr(state, "roles", None)
    if not roles:
        return None
    try:
        saved = roles.store.load()
    except ProfileError as exc:
        # Fail closed: an unreadable library may still reference this avatar.
        logger.warning("讀取角色設定失敗，暫不允許覆寫數字人 %s：%s", avatar_id, exc)
        return f"角色設定檔無法讀取（{exc}），無法確認此人物素材未被引用，暫不允許覆寫"
    if any(profile["avatar_id"] == avatar_id
           for library in (roles.library, saved) for profile in library["profiles"]):
        return "請先解除角色設定檔對此人物素材的引用，再覆寫"
    return None


async def import_avatar(request):
    """Accept one closed-mouth video and start building an avatar from it.

    Text fields come first; the single ``video`` part must be last so that the
    request is fully validated before any byte is written to disk.
    """
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    upload_dir = None
    handed_off = False
    try:
        reader = await request.multipart()
        engine = ""
        avatar_id = ""
        overwrite = False
        green_screen = False
        quality = None
        video_path = None
        original_name = "upload.mp4"
        size = 0

        while True:
            part = await reader.next()
            if part is None:
                break
            if video_path is not None:
                msg = "只能上傳一部影片" if part.name == "video" else "影片必須是表單最後一個欄位"
                return _json({"code": -1, "msg": msg}, status=400)
            if part.name == "type":
                engine = (await part.text()).strip()
            elif part.name == "avatar_id":
                avatar_id = (await part.text()).strip()
            elif part.name == "overwrite":
                overwrite = (await part.text()).strip().lower() in {"1", "true", "yes"}
            elif part.name == "green_screen":
                green_screen = (await part.text()).strip().lower() in {"1", "true", "yes"}
            elif part.name == "quality":
                raw = (await part.text()).strip()
                if not raw:
                    continue
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    return _json({"code": -1, "msg": "嘴型參數格式不正確"}, status=400)
                if not isinstance(parsed, dict):
                    return _json({"code": -1, "msg": "嘴型參數必須是物件"}, status=400)
                try:
                    state.avatar_service.normalize_quality(parsed)
                except ServiceError as exc:
                    return _json({"code": -1, "msg": str(exc)}, status=400)
                quality = parsed
            elif part.name == "video":
                original_name = part.filename or original_name
                suffix = Path(original_name).suffix.lower() or ".mp4"
                if suffix not in VIDEO_EXTS:
                    return _json({"code": -1, "msg": "請上傳 mp4 / mov / webm / avi 影片"}, status=400)
                engine, avatar_id = validate_import_request(
                    engine=engine,
                    avatar_id=avatar_id,
                    original_name=original_name,
                    overwrite=overwrite,
                    session_count=_active_session_count(),
                )
                # Checked again by the builder right before installing.
                if overwrite and (conflict := await asyncio.to_thread(_avatar_replace_conflict, avatar_id)):
                    return _json({"code": -1, "msg": conflict}, status=409)
                upload_dir = state.avatar_service.uploads_dir() / uuid4_name()
                upload_dir.mkdir(parents=True, exist_ok=True)
                video_path = upload_dir / f"source{suffix}"
                with video_path.open("wb") as handle:
                    while chunk := await part.read_chunk(size=1024 * 1024):
                        size += len(chunk)
                        if size > MAX_IMPORT_VIDEO_BYTES:
                            limit_mb = MAX_IMPORT_VIDEO_BYTES // (1024 * 1024)
                            return _json({"code": -1, "msg": f"影片不可超過 {limit_mb} MB"}, status=413)
                        await asyncio.to_thread(handle.write, chunk)

        if video_path is None or size == 0:
            return _json({"code": -1, "msg": "請選擇要匯入的影片"}, status=400)

        job = start_import_job(
            engine=engine,
            video_path=video_path,
            original_name=original_name,
            avatar_id=avatar_id,
            overwrite=overwrite,
            session_count=_active_session_count(),
            quality=quality if quality is not None else state.avatar_service.quality_from_model(state.config.model),
            green_screen=green_screen,
            replace_guard=_avatar_replace_conflict,
        )
        handed_off = True
        if quality is not None:
            # Remember the accepted build settings only once the import has started.
            try:
                apply_mouth_quality(state.config, quality, avatars=state.avatar_service)
            except Exception:
                logger.exception("儲存匯入用的嘴型參數失敗")
        return _json({"code": 0, "msg": "ok", "data": job.to_dict()})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception:
        logger.exception("匯入數字人失敗")
        return _json({"code": -1, "msg": "匯入數字人失敗，請查看伺服器日誌"}, status=500)
    finally:
        if upload_dir is not None and not handed_off:
            await asyncio.to_thread(discard_upload, upload_dir)


async def import_avatar_status(request):
    job_id = request.match_info.get("job_id", "")
    job = get_job(job_id)
    if job is None:
        return _json({"code": -1, "msg": "找不到製作任務"}, status=404)
    return _json({"code": 0, "data": job.to_dict()})


def uuid4_name() -> str:
    import uuid

    return uuid.uuid4().hex[:12]
