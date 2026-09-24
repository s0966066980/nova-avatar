# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""執行時設定 API：Ollama 模型、數字人引擎與角色。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

from aiohttp import web

from src.avatars.builder import uploads_dir
from src.avatars.catalog import (
    archive_avatar, delete_archived_avatar, list_archived_avatars,
    resolve_preview_path, restore_avatar,
)
from src.server.import_jobs import VIDEO_EXTS, get_job, import_in_progress, start_import_job
from src.server.runtime_settings import (
    SettingsError,
    apply_avatar,
    apply_llm_model,
    apply_mouth_quality,
    apply_stt_settings,
    apply_tts_settings,
    apply_vad_settings,
    apply_stage_settings,
    apply_stage_background,
    current_snapshot,
    fetch_llm_catalog,
    quality_from_model,
    vad_snapshot,
    speech_snapshot,
    stage_snapshot,
    apply_reply_rules,
    reply_rules_snapshot,
)
from src.server.state import state
from src.scene.service import (
    MAX_BACKGROUND_BYTES,
    SceneError,
    add_background,
    archive_background,
    backgrounds_root,
    list_archived_backgrounds,
    list_backgrounds,
    preview_path as background_preview_path,
    render_avatar_preview,
    restore_background,
    scene_service,
)
from src.utils.logging import logger


def _json(payload: dict, status: int = 200) -> web.Response:
    return web.Response(
        status=status,
        content_type="application/json",
        text=json.dumps(payload, ensure_ascii=False),
    )


def _active_session_count() -> int:
    return sum(1 for stream in state.avatar_streams.values() if stream is not None)


async def get_settings(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    data = current_snapshot(state.config)
    data["session_count"] = _active_session_count()
    data["switching"] = bool(getattr(state, "switching", False))
    data["ready"] = bool(state.server_ready)
    data["model_ready"] = bool(getattr(state, "model_ready", False))
    return _json({"code": 0, "data": data})


async def get_llm_rules(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    return _json({"code": 0, "data": reply_rules_snapshot(state.config)})


async def set_llm_rules(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        params = await request.json()
        result = apply_reply_rules(
            state.config,
            params.get("rules"),
            params.get("expected_revision"),
        )
        return _json({"code": 0, "msg": "ok", "data": result})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        logger.exception("更新 LLM 回覆規則失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def list_llm_models(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    result = await fetch_llm_catalog(state.config)
    return _json({"code": 0, "data": result})


async def set_llm_model(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        params = await request.json()
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: apply_llm_model(
                state.config,
                params.get("model", ""),
                params.get("provider", ""),
                params.get("system_prompt"),
                params.get("response_max_chars"),
                params.get("reply_mode"),
                params.get("board_max_items"),
                params.get("assistant_profile"),
                params.get("semantic_wait_seconds"),
            ),
        )
        return _json({"code": 0, "msg": "ok", "data": result})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        logger.exception("切換 LLM 模型失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def get_vad_settings(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    return _json({"code": 0, "data": vad_snapshot(state.config)})


async def set_vad_settings(request):
    """更新 Silero VAD 端點引數。"""
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        params = await request.json()
        loop = asyncio.get_event_loop()
        # 切 silero 會載入模型，別卡住事件迴圈
        result = await loop.run_in_executor(
            None, lambda: apply_vad_settings(state.config, params)
        )
        return _json({"code": 0, "msg": "ok", "data": result})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        logger.exception("切換 VAD 設定失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def get_speech_settings(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    return _json({"code": 0, "data": speech_snapshot(state.config)})


async def get_stage_settings(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    return _json({"code": 0, "data": stage_snapshot(state.config)})


async def set_stage_settings(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        params = await request.json()
        result = apply_stage_settings(state.config, params)
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
        "items": list_backgrounds(),
        **scene_service.snapshot(),
    }})


async def upload_background(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    root = backgrounds_root()
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
                if size > MAX_BACKGROUND_BYTES:
                    return _json({"code": -1, "msg": "背景檔案不可超過 100 MB"}, status=413)
                handle.write(chunk)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, add_background, temporary, original_name)
        return _json({"code": 0, "msg": "ok", "data": result})
    except SceneError as exc:
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
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            apply_stage_background,
            state.config,
            params.get("background_id", ""),
        )
        return _json({"code": 0, "msg": "ok", "data": result})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        logger.exception("切換舞台背景失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def background_preview(request):
    try:
        return web.FileResponse(background_preview_path(request.match_info["background_id"]))
    except SceneError:
        raise web.HTTPNotFound()


async def delete_background(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    background_id = request.match_info.get("background_id", "")
    if background_id in {
        scene_service.snapshot()["background_id"],
        str(getattr(state.config.stage, "background_id", "") or ""),
    }:
        return _json({"code": -1, "msg": "正在使用的背景無法刪除，請先切換背景"}, status=409)
    try:
        archived = archive_background(background_id)
        return _json({"code": 0, "msg": "ok", "data": {
            "background_id": background_id, "archived_as": archived.name,
        }})
    except SceneError as exc:
        return _json({"code": -1, "msg": str(exc)}, status=404)
    except Exception as exc:
        logger.exception("刪除舞台背景失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def archived_backgrounds(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    return _json({"code": 0, "data": {"items": list_archived_backgrounds()}})


async def restore_archived_background(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        background_id = restore_background(request.match_info.get("archive_name", ""))
        return _json({"code": 0, "msg": "ok", "data": {"background_id": background_id}})
    except SceneError as exc:
        return _json({"code": -1, "msg": str(exc)}, status=409)
    except Exception as exc:
        logger.exception("復原舞台背景失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def set_stt_settings(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        params = await request.json()
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: apply_stt_settings(
                state.config, params, session_count=_active_session_count()
            ),
        )
        return _json({"code": 0, "msg": "ok", "data": result})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        logger.exception("切換 STT 失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def set_tts_settings(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        params = await request.json()
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: apply_tts_settings(
                state.config, params, session_count=_active_session_count()
            ),
        )
        return _json({"code": 0, "msg": "ok", "data": result})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        logger.exception("切換 TTS 失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def pick_speech_path(request):
    """Open a native local chooser; browser file inputs cannot reveal paths."""
    try:
        kind = (await request.json()).get("kind", "file")
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory() if kind == "directory" else filedialog.askopenfilename(
            filetypes=[("Audio files", "*.wav *.mp3 *.flac *.m4a *.ogg"), ("All files", "*")]
        )
        root.destroy()
        return _json({"code": 0, "msg": "ok", "data": {"path": path}})
    except Exception as exc:
        return _json({"code": -1, "msg": f"無法開啟本機檔案選擇器：{exc}"}, status=500)


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
        )
        return _json({"code": 0, "msg": "ok", "data": result})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        logger.exception("切換數字人失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def set_mouth_quality(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        params = await request.json()
        result = apply_mouth_quality(state.config, params or {})
        return _json({"code": 0, "msg": "ok", "data": result})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        logger.exception("套用嘴型畫質失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def avatar_preview(request):
    avatar_id = request.match_info.get("avatar_id", "")
    preview = resolve_preview_path(avatar_id)
    if preview is None or not preview.is_file():
        return _json({"code": -1, "msg": "預覽圖不存在"}, status=404)
    return web.FileResponse(preview)


async def avatar_scene_preview(request):
    avatar_id = request.match_info.get("avatar_id", "")
    try:
        loop = asyncio.get_running_loop()
        image = await loop.run_in_executor(None, render_avatar_preview, avatar_id)
        return web.Response(body=image, content_type="image/jpeg", headers={"Cache-Control": "no-store"})
    except SceneError:
        raise web.HTTPNotFound()


async def delete_avatar(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    avatar_id = request.match_info.get("avatar_id", "")
    if avatar_id == state.config.model.avatar_id:
        return _json({"code": -1, "msg": "正在使用的數字人無法刪除，請先切換角色"}, status=409)
    if _active_session_count():
        return _json({"code": -1, "msg": "請先結束連線再刪除數字人"}, status=409)
    if import_in_progress():
        return _json({"code": -1, "msg": "數字人正在製作，請稍後再刪除"}, status=409)
    try:
        archived = archive_avatar(avatar_id)
        return _json({"code": 0, "msg": "ok", "data": {
            "avatar_id": avatar_id, "archived_as": archived.name,
        }})
    except ValueError as exc:
        return _json({"code": -1, "msg": str(exc)}, status=404)
    except Exception as exc:
        logger.exception("刪除數字人失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def archived_avatars(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    return _json({"code": 0, "data": {"items": list_archived_avatars()}})


async def restore_archived_avatar(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    if import_in_progress():
        return _json({"code": -1, "msg": "數字人正在製作，請稍後再復原"}, status=409)
    try:
        avatar_id = restore_avatar(request.match_info.get("archive_name", ""))
        return _json({"code": 0, "msg": "ok", "data": {"avatar_id": avatar_id}})
    except ValueError as exc:
        return _json({"code": -1, "msg": str(exc)}, status=409)
    except Exception as exc:
        logger.exception("復原數字人失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def delete_archived_avatar_permanently(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        avatar_id = delete_archived_avatar(request.match_info.get("archive_name", ""))
        return _json({"code": 0, "msg": "ok", "data": {"avatar_id": avatar_id}})
    except ValueError as exc:
        return _json({"code": -1, "msg": str(exc)}, status=404)
    except Exception as exc:
        logger.exception("永久刪除封存數字人失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def import_avatar(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        reader = await request.multipart()
        engine = ""
        avatar_id = ""
        overwrite = False
        green_screen = False
        quality = None
        video_path = None
        original_name = "upload.mp4"

        while True:
            part = await reader.next()
            if part is None:
                break
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
                quality = parsed
            elif part.name == "video":
                original_name = part.filename or original_name
                suffix = Path(original_name).suffix.lower() or ".mp4"
                if suffix not in VIDEO_EXTS:
                    return _json({"code": -1, "msg": "請上傳 mp4 / mov / webm / avi 影片"}, status=400)
                dest_dir = uploads_dir() / uuid4_name()
                dest_dir.mkdir(parents=True, exist_ok=True)
                video_path = dest_dir / f"source{suffix}"
                with video_path.open("wb") as handle:
                    while True:
                        chunk = await part.read_chunk()
                        if not chunk:
                            break
                        handle.write(chunk)

        if video_path is None or not video_path.is_file() or video_path.stat().st_size == 0:
            return _json({"code": -1, "msg": "請選擇要匯入的影片"}, status=400)

        if quality is not None:
            quality = apply_mouth_quality(state.config, quality)
        else:
            quality = quality_from_model(state.config.model)

        job = start_import_job(
            engine=engine,
            video_path=video_path,
            original_name=original_name,
            avatar_id=avatar_id,
            overwrite=overwrite,
            session_count=_active_session_count(),
            quality=quality,
            green_screen=green_screen,
        )
        return _json({"code": 0, "msg": "ok", "data": job.to_dict()})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        logger.exception("匯入數字人失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def import_avatar_status(request):
    job_id = request.match_info.get("job_id", "")
    job = get_job(job_id)
    if job is None:
        return _json({"code": -1, "msg": "找不到製作任務"}, status=404)
    return _json({"code": 0, "data": job.to_dict()})


def uuid4_name() -> str:
    import uuid

    return uuid.uuid4().hex[:12]
