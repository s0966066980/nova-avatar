# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""設定 API：語音辨識、語音活動偵測、語音合成聲音與聲線模型。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from aiohttp import web
from nova_core.server.runtime_settings import (
    breezyvoice_server_ready,
    preview_profile_voice,
    SettingsError,
    apply_stt_settings,
    apply_vad_settings,
    vad_snapshot,
    speech_snapshot,
    stt_snapshot,
)
from nova_core.server.deferred_settings import defer_when_connected
from nova_core.server.state import state
from nova_contracts.tts import MAX_VOICE_UPLOAD_BYTES, TtsError, VoiceRef, VoiceUpload
from nova_core.utils.logging import logger
from nova_core.server.routes.settings.shared import _json, _active_session_count


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
    return _json({"code": 0, "data": await asyncio.to_thread(speech_snapshot, state.config, tts=state.tts)})


@defer_when_connected("語音辨識", stt_snapshot)
async def set_stt_settings(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        params = await request.json()
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: apply_stt_settings(
                state.config, params, session_count=_active_session_count(),
                stt=state.stt,
            ),
        )
        return _json({"code": 0, "msg": "ok", "data": result})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        logger.exception("切換 STT 失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def list_tts_voices(request):
    voices = await asyncio.to_thread(state.tts.list_voices)
    return _json({"code": 0, "data": {"items": [voice.model_dump(mode="json") for voice in voices.voices]}})


async def tts_voice_audio(request):
    """The stored WAV of a library voice, for previewing it in the console."""
    ref = VoiceRef(voice_id=request.match_info.get("voice_id", ""))
    try:
        audio = await asyncio.to_thread(state.tts.voice_audio, ref)
    except TtsError as exc:
        return _json({"code": -1, "msg": exc.message}, status=exc.status)
    return web.Response(body=audio, headers={"Content-Type": "audio/wav", "Cache-Control": "no-store"})


async def breezyvoice_status(request):
    """Whether a profile's BreezyVoice server is up; the console shows "starting" otherwise."""
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    params = {key: request.query.get(key, "") for key in ("model", "tts_server")}
    try:
        ready = await asyncio.to_thread(breezyvoice_server_ready, state.config, params, tts=state.tts)
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    return _json({"code": 0, "data": {"ready": ready}})


async def preview_voice(request):
    """Synthesize a short sentence with a profile's unsaved voice for the profile editor."""
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        body = await request.json()
    except Exception:
        body = None
    tts = body.get("tts") if isinstance(body, dict) else None
    if not isinstance(tts, dict):
        return _json({"code": -1, "msg": "請提供要試聽的聲音設定"}, status=400)
    try:
        # Starting BreezyVoice and synthesizing both take seconds to minutes.
        audio = await asyncio.to_thread(preview_profile_voice, state.config, tts,
                                        session_count=_active_session_count(), tts=state.tts)
        return _json({"code": 0, "msg": "ok", "data": {"audio": audio}})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception:
        logger.exception("設定檔聲音試聽失敗")
        return _json({"code": -1, "msg": "聲音試聽失敗"}, status=500)


class _FieldTooLong(ValueError):
    pass


async def _read_field(part, limit: int = 1024) -> str:
    data = bytearray()
    while chunk := await part.read_chunk(size=limit):
        data.extend(chunk)
        if len(data) > limit:
            raise _FieldTooLong("欄位內容過長")
    return data.decode("utf-8", "replace")


async def upload_tts_voice(request):
    """Add reference audio to the voice library: read with a cap, then the TTS layer validates and converts."""
    try:
        reader = await request.multipart()
        name, transcript, stem, audio = "", "", "", None
        while (part := await reader.next()) is not None:
            if part.name == "name":
                name = (await _read_field(part)).strip()
            elif part.name == "transcript":
                transcript = (await _read_field(part, limit=4096)).strip()
            elif part.name == "voice" and part.filename and audio is None:
                stem = Path(part.filename).stem
                data = bytearray()
                while chunk := await part.read_chunk(size=256 * 1024):
                    data.extend(chunk)
                    if len(data) > MAX_VOICE_UPLOAD_BYTES:
                        limit = MAX_VOICE_UPLOAD_BYTES / 1024 / 1024
                        return _json({"code": -1, "msg": f"參考音訊不可超過 {limit:g} MB"}, status=413)
                audio = bytes(data)
            else:
                return _json({"code": -1, "msg": "上傳欄位不正確"}, status=400)
        if audio is None:
            return _json({"code": -1, "msg": "請選擇參考音訊檔"}, status=400)
        upload = VoiceUpload(name=name or stem, transcript=transcript)
        voice = await asyncio.to_thread(state.tts.add_voice, audio, upload)
        return _json({"code": 0, "msg": "ok", "data": voice.model_dump(mode="json")})
    except _FieldTooLong as exc:
        return _json({"code": -1, "msg": str(exc)}, status=400)
    except TtsError as exc:
        return _json({"code": -1, "msg": exc.message}, status=exc.status)
    except Exception:
        logger.exception("上傳參考音訊失敗")
        return _json({"code": -1, "msg": "上傳參考音訊失敗"}, status=500)


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
        raise TtsError("這段參考音訊正在使用中，請先改用其他聲音", status=409)
    state.tts.delete_voice(VoiceRef(voice_id=voice_id))


async def delete_tts_voice(request):
    """Move an unused voice to the library's recycle bin."""
    voice_id = request.match_info.get("voice_id", "")
    try:
        await asyncio.to_thread(_archive_unused_voice, voice_id)
        return _json({"code": 0, "msg": "ok", "data": {"id": voice_id}})
    except TtsError as exc:
        return _json({"code": -1, "msg": exc.message}, status=exc.status)


def _archive_unused_voice_model(voice_id: str) -> None:
    if _voice_in_use(voice_id):
        raise TtsError("這個聲線模型正在使用中，請先讓使用它的角色改用其他聲音", status=409)
    state.tts.delete_voice_model(VoiceRef(voice_id=voice_id))


async def delete_tts_voice_model(request):
    """Move an unused voice model to the recycle bin under ``models/tts/.deleted``."""
    voice_id = request.match_info.get("voice_id", "")
    try:
        await asyncio.to_thread(_archive_unused_voice_model, voice_id)
        return _json({"code": 0, "msg": "ok", "data": {"id": voice_id}})
    except TtsError as exc:
        return _json({"code": -1, "msg": exc.message}, status=exc.status)
