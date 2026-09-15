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
            avatar_stream.put_msg_txt(params['text'])
            response_text = params['text']
            response_payload = {
                "code": 0,
                "msg": "ok",
                "response": response_text,
            }
        elif params['type'] == 'chat':
            voice_session = state.voice_sessions.get(sessionid)
            if voice_session is None or avatar_stream is None:
                raise web.HTTPConflict(text="語音工作階段尚未連線")
            if not getattr(voice_session, "event_sink_ready", True):
                raise web.HTTPConflict(text="回覆事件通道尚未就緒，請稍後再試")
            started = await voice_session.start_text_turn(
                params['text'],
                interrupt=bool(params.get('interrupt')),
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
