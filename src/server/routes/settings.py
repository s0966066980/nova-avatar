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
from src.avatars.mouth_quality import QualityError, normalize_quality
from src.server.import_jobs import (
    MAX_IMPORT_VIDEO_BYTES, VIDEO_EXTS, discard_upload, get_job, import_in_progress,
    start_import_job, validate_import_request,
)
from src.server.runtime_settings import (
    apply_video_settings,
    SettingsError,
    apply_avatar,
    apply_llm_model,
    apply_llm_behavior,
    apply_mouth_quality,
    apply_stt_settings,
    apply_tts_settings,
    validate_tts_sources,
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
from src.server.deferred_settings import defer_when_connected, snapshot as pending_snapshot
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
from src.tts import voice_library
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
    data["pending_settings"] = pending_snapshot()
    data["session_count"] = _active_session_count()
    data["switching"] = bool(state.switching or state.settings_applying)
    data["ready"] = bool(state.server_ready)
    data["model_ready"] = bool(getattr(state, "model_ready", False))
    roles = getattr(state, "roles", None)
    data["roles"] = roles.snapshot() if roles else None
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


async def set_llm_behavior(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        params = await request.json()
        result = apply_llm_behavior(state.config, params.get("assistant_profile"),
                                    params.get("rules"), params.get("expected_revision"))
        return _json({"code": 0, "msg": "ok", "data": result})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        logger.exception("儲存 Prompt 與規則失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


@defer_when_connected("對話模型", lambda config: current_snapshot(config)["llm"])
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


@defer_when_connected("收音設定", vad_snapshot)
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
        main = roles.profiles[roles.library["pair"]["main"]] if roles is not None else None
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


@defer_when_connected("語音辨識", lambda config: speech_snapshot(config)["stt"])
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
    """Reject unsafe sources before the request is applied or saved for later."""
    if state.config:
        try:
            params = await request.json()
        except (ValueError, TypeError):
            return _json({"code": -1, "msg": "設定格式不正確"}, status=400)
        try:
            await asyncio.to_thread(validate_tts_sources, state.config, params)
        except SettingsError as exc:
            return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    return await _apply_tts_settings(request)


@defer_when_connected("語音合成", lambda config: speech_snapshot(config)["tts"])
async def _apply_tts_settings(request):
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


async def list_tts_voices(request):
    return _json({"code": 0, "data": {"items": await asyncio.to_thread(voice_library.list_voices)}})


async def _read_field(part, limit: int = 1024) -> str:
    data = bytearray()
    while chunk := await part.read_chunk(size=limit):
        data.extend(chunk)
        if len(data) > limit:
            raise voice_library.VoiceLibraryError("欄位內容過長")
    return data.decode("utf-8", "replace")


async def upload_tts_voice(request):
    """Add reference audio to the voice library: stream, cap, validate, convert."""
    root = voice_library.voices_root()
    temporary = root / f".upload-{uuid4().hex}"
    try:
        root.mkdir(parents=True, exist_ok=True)
        reader = await request.multipart()
        name, stem, received = "", "", False
        while (part := await reader.next()) is not None:
            if part.name == "name":
                name = (await _read_field(part)).strip()
            elif part.name == "voice" and part.filename and not received:
                stem = Path(part.filename).stem
                size = 0
                with temporary.open("wb") as handle:
                    while chunk := await part.read_chunk(size=256 * 1024):
                        size += len(chunk)
                        if size > voice_library.MAX_UPLOAD_BYTES:
                            limit = voice_library.MAX_UPLOAD_BYTES / 1024 / 1024
                            return _json({"code": -1, "msg": f"參考音訊不可超過 {limit:g} MB"}, status=413)
                        handle.write(chunk)
                received = True
            else:
                return _json({"code": -1, "msg": "上傳欄位不正確"}, status=400)
        if not received:
            return _json({"code": -1, "msg": "請選擇參考音訊檔"}, status=400)
        voice = await asyncio.to_thread(voice_library.add_voice, temporary, name or stem)
        return _json({"code": 0, "msg": "ok", "data": voice})
    except voice_library.VoiceLibraryError as exc:
        return _json({"code": -1, "msg": exc.message}, status=exc.status)
    except Exception:
        logger.exception("上傳參考音訊失敗")
        return _json({"code": -1, "msg": "上傳參考音訊失敗"}, status=500)
    finally:
        temporary.unlink(missing_ok=True)


def _voice_in_use(voice_id: str) -> bool:
    if state.config is not None and getattr(state.config.tts, "ref_file", "") == voice_id:
        return True
    roles = getattr(state, "roles", None)
    if roles is None:
        return False
    libraries = [getattr(roles, "library", None) or {}]
    try:
        libraries.append(roles.store.load())
    except Exception:
        logger.warning("讀取角色設定失敗，無法確認參考音訊是否仍被引用")
        return True
    return any(profile.get("tts", {}).get("ref_file") == voice_id
               for library in libraries for profile in library.get("profiles", []))


def _archive_unused_voice(voice_id: str) -> None:
    if _voice_in_use(voice_id):
        raise voice_library.VoiceLibraryError("這段參考音訊正在使用中，請先改用其他聲音", status=409)
    voice_library.delete_voice(voice_id)


async def delete_tts_voice(request):
    """Move an unused voice to the library's recycle bin."""
    voice_id = request.match_info.get("voice_id", "")
    try:
        await asyncio.to_thread(_archive_unused_voice, voice_id)
        return _json({"code": 0, "msg": "ok", "data": {"id": voice_id}})
    except voice_library.VoiceLibraryError as exc:
        return _json({"code": -1, "msg": exc.message}, status=exc.status)


@defer_when_connected("數位人引擎", lambda config: current_snapshot(config)["avatar"])
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


async def set_video_output(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        result = apply_video_settings(state.config, await request.json())
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


def _avatar_replace_conflict(avatar_id: str) -> str | None:
    """Why an existing avatar must not be replaced by an import, or None."""
    config = state.config
    if config is not None and avatar_id == config.model.avatar_id:
        return "正在使用的數字人無法覆寫，請先切換角色"
    roles = getattr(state, "roles", None)
    if roles and any(
        profile["avatar_id"] == avatar_id
        for library in (roles.library, roles.store.load())
        for profile in library["profiles"]
    ):
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
                    normalize_quality(parsed)
                except QualityError as exc:
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
                if overwrite and (conflict := _avatar_replace_conflict(avatar_id)):
                    return _json({"code": -1, "msg": conflict}, status=409)
                upload_dir = uploads_dir() / uuid4_name()
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
            quality=quality if quality is not None else quality_from_model(state.config.model),
            green_screen=green_screen,
            replace_guard=_avatar_replace_conflict,
        )
        handed_off = True
        if quality is not None:
            # Remember the accepted build settings only once the import has started.
            try:
                apply_mouth_quality(state.config, quality)
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
