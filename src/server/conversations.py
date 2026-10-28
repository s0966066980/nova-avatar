# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Session-owned language and memory settings; persistent defaults are separate."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import asdict

from aiohttp import web

from src.config.schema import ConversationConfig
from src.config.overrides import persist_runtime_overrides
from src.llm.service import session_memory
from src.server.state import state


VOICES = {
    'zh-TW': [
        {'id': 'zh-TW-HsiaoChenNeural', 'label': '曉臻（女聲）'},
        {'id': 'zh-TW-HsiaoYuNeural', 'label': '曉雨（女聲）'},
        {'id': 'zh-TW-YunJheNeural', 'label': '雲哲（男聲）'},
    ],
    'en-US': [
        {'id': 'en-US-JennyNeural', 'label': 'Jenny（美式女聲）'},
        {'id': 'en-US-AriaNeural', 'label': 'Aria（美式女聲）'},
        {'id': 'en-US-GuyNeural', 'label': 'Guy（美式男聲）'},
    ],
}


def defaults(config) -> dict:
    return asdict(getattr(config, 'conversation', ConversationConfig()))


def validate(values: dict, current: dict) -> dict:
    if not isinstance(values, dict) or set(values) - set(current):
        raise ValueError('無效的對話設定欄位')
    candidate = {**current, **values}
    if candidate['locale'] not in VOICES:
        raise ValueError('不支援的語系')
    limit = candidate['history_max_messages']
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 2000:
        raise ValueError('歷史訊息上限須為 1–2000 的整數')
    for locale, key in [('zh-TW', 'voice_zh_tw'), ('en-US', 'voice_en_us')]:
        if candidate[key] not in {voice['id'] for voice in VOICES[locale]}:
            raise ValueError('聲音與語系不符，請從聲音清單選擇')
    return candidate


def check_language_support(config, locale: str) -> None:
    if locale == 'en-US' and getattr(config.asr, 'type', '') != 'whisper':
        raise ValueError('english_requires_whisper')
    if locale == 'en-US' and getattr(config.tts, 'type', '') != 'edgetts':
        raise ValueError('english_requires_edge_tts')


def configure_avatar(avatar, values: dict) -> None:
    config = getattr(avatar, 'config', None)
    if config is None:
        return
    config.conversation = ConversationConfig(**values)
    profile = deepcopy(config.llm.assistant_profile)
    profile.output_locale = values['locale']
    config.llm.assistant_profile = profile
    if config.tts.type == 'edgetts':
        config.tts.ref_file = values['voice_en_us' if values['locale'] == 'en-US' else 'voice_zh_tw']


async def warm_voice(config, values: dict) -> None:
    if getattr(config.tts, 'type', '') == 'edgetts':
        from src.tts.engines.edge import prewarm_edge_tts
        voice = values['voice_en_us' if values['locale'] == 'en-US' else 'voice_zh_tw']
        ready = await asyncio.to_thread(prewarm_edge_tts, voice, decode_pcm=True,
                                        keep_connection=True, timeout_seconds=5)
        if not ready:
            raise RuntimeError('voice_unavailable')


def snapshot(session) -> dict:
    settings = dict(session._conversation)
    return {
        'sessionid': session.sessionid, 'role': session._presenter,
        **settings, 'switching': session._settings_switching,
        'pending_history_max_messages': session._pending_history_limit,
        'idle_reset_seconds': session._idle_reset_delay() if session._presenter == 'stage' else 0,
        'full_reset_seconds': 120 if session._presenter == 'stage' else 0,
        'memory': session_memory(session.sessionid, settings['history_max_messages']),
    }


async def list_conversations(request):
    if state.config is None:
        return web.json_response({'code': -1, 'msg': '服務尚未就緒'}, status=503)
    capacity = None
    if getattr(state.config.llm, 'provider', '') == 'llamacpp':
        from src.llm.context_usage import deployed_capacity
        capacity = await asyncio.to_thread(deployed_capacity, state.config.llm.base_url)
    return web.json_response({'code': 0, 'data': {
        'model_context': {'model': state.config.llm.model, 'capacity': capacity},
        'defaults': defaults(state.config), 'voices': VOICES,
        'sessions': [snapshot(session) for session in list(state.voice_sessions.values())],
    }})


async def save_defaults(request):
    if state.config is None:
        return web.json_response({'code': -1, 'msg': '服務尚未就緒'}, status=503)
    try:
        values = validate(await request.json(), defaults(state.config))
        previous = getattr(state.config, 'conversation', ConversationConfig())
        state.config.conversation = ConversationConfig(**values)
        try:
            persist_runtime_overrides(state.config)
        except Exception:
            state.config.conversation = previous
            raise
        return web.json_response({'code': 0, 'data': values})
    except (ValueError, TypeError) as exc:
        return web.json_response({'code': -1, 'msg': str(exc)}, status=400)
    except OSError:
        return web.json_response({'code': -1, 'msg': '儲存失敗，已保留上一份預設，請重試'}, status=503)


async def update_conversation(request):
    session = state.voice_sessions.get(int(request.match_info['sessionid']))
    if session is None:
        return web.json_response({'code': -1, 'msg': '對話已結束，請重新選擇'}, status=404)
    try:
        await session.apply_conversation(await request.json())
        return web.json_response({'code': 0, 'data': snapshot(session)})
    except (ValueError, TypeError, RuntimeError) as exc:
        return web.json_response({'code': -1, 'msg': str(exc)}, status=409)


async def clear_conversation(request):
    session = state.voice_sessions.get(int(request.match_info['sessionid']))
    if session is None:
        return web.json_response({'code': -1, 'msg': '對話已結束，請重新選擇'}, status=404)
    async with session._settings_lock:
        capture, paused = session._capture_requested, session._manual_pause
        try:
            await session.interrupt()
            session.reset_conversation()
        finally:
            session._capture_requested, session._manual_pause = capture, paused
            session._refresh_gate()
    return web.json_response({'code': 0, 'data': snapshot(session)})
