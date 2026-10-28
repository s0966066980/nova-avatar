# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""聊天相關路由"""
import json
from aiohttp import web

from src.llm.service import clear_session_history
from src.utils.logging import logger
from src.server.state import state


async def human(request):
    """處理文本對話請求"""
    try:
        params = await request.json()
        sessionid = params.get('sessionid', 0)
        avatar_stream = state.avatar_streams.get(sessionid)

        if params['type'] == 'echo':
            if avatar_stream is None:
                raise KeyError(sessionid)
            voice_session = state.voice_sessions.get(sessionid)
            if voice_session is None:
                raise web.HTTPConflict(text="語音工作階段尚未連線")
            started = await voice_session.start_read_aloud_turn(
                params['text'],
                interrupt=bool(params.get('interrupt')),
            )
            response_text = params['text']
            response_payload = {
                "code": 0,
                "msg": "ok",
                "response": response_text,
                **started,
            }
        elif params['type'] == 'chat':
            voice_session = state.voice_sessions.get(sessionid)
            if voice_session is None or avatar_stream is None:
                raise web.HTTPConflict(text="語音工作階段尚未連線")
            if not getattr(voice_session, "event_sink_ready", True):
                raise web.HTTPConflict(text="回覆事件通道尚未就緒，請稍後再試")
            if getattr(voice_session, '_presenter', 'console') == 'stage' and not getattr(state.config.stage, 'composer_enabled', False):
                raise web.HTTPConflict(text='composer_disabled')
            store = getattr(voice_session, 'attachments', None)
            selection = params.get('attachments', store.selection if store else [])
            try:
                if store:
                    store.validate_selection(selection)
                elif selection:
                    raise ValueError('missing_attachment')
            except ValueError as exc:
                raise web.HTTPBadRequest(text=str(exc)) from exc
            if selection:
                import asyncio
                from src.server.attachments import vision_ready
                if not await asyncio.to_thread(vision_ready, state.config):
                    raise web.HTTPConflict(text='vision_unavailable')
            request_id = params.get('request_id')
            if request_id is not None and (not isinstance(request_id, str) or not 1 <= len(request_id) <= 64):
                raise web.HTTPBadRequest(text='invalid_request')
            started = await voice_session.start_text_turn(
                params.get('text', ''),
                interrupt=bool(params.get('interrupt')),
                **({'attachments': selection} if store else {}),
                **({'request_id': request_id} if request_id else {}),
            )
            response_payload = {
                "code": 0,
                "msg": "accepted",
                **started,
            }
        else:
            raise web.HTTPBadRequest(text="不支援的訊息類型")

        return web.Response(
            content_type="application/json",
            text=json.dumps(response_payload),
        )
    except web.HTTPException:
        raise
    except Exception as e:
        logger.exception('exception:')
        return web.Response(
            content_type="application/json",
            text=json.dumps(
                {"code": -1, "msg": str(e)}
            ),
        )


async def interrupt_talk(request):
    """中斷當前對話"""
    try:
        params = await request.json()
        sessionid = params.get('sessionid', 0)
        voice_session = state.voice_sessions.get(sessionid)
        if voice_session is not None:
            if params.get('request_id'):
                await voice_session.cancel_text_request(params['request_id'])
            else:
                await voice_session.interrupt()
        else:
            state.avatar_streams[sessionid].flush_talk()
        
        return web.Response(
            content_type="application/json",
            text=json.dumps(
                {"code": 0, "msg": "ok"}
            ),
        )
    except Exception as e:
        logger.exception('exception:')
        return web.Response(
            content_type="application/json",
            text=json.dumps(
                {"code": -1, "msg": str(e)}
            ),
        )


async def is_speaking(request):
    """查詢是否正在說話"""
    params = await request.json()
    sessionid = params.get('sessionid', 0)
    
    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"code": 0, "data": state.avatar_streams[sessionid].is_speaking()}
        ),
    )


async def clear_history(request):
    """清空對話歷史"""
    try:
        params = await request.json()
        sessionid = params.get('sessionid', 0)
        
        voice_session = state.voice_sessions.get(sessionid)
        if voice_session is not None:
            capture, paused = voice_session._capture_requested, voice_session._manual_pause
            try:
                await voice_session.interrupt()
                voice_session.reset_conversation()
            finally:
                voice_session._capture_requested, voice_session._manual_pause = capture, paused
                voice_session._refresh_gate()
        else:
            clear_session_history(sessionid)
        
        return web.Response(
            content_type="application/json",
            text=json.dumps(
                {"code": 0, "msg": "對話歷史已清空"}
            ),
        )
    except Exception as e:
        logger.exception('清空歷史失敗:')
        return web.Response(
            content_type="application/json",
            text=json.dumps(
                {"code": -1, "msg": str(e)}
            ),
        )
