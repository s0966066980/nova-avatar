# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""影片相關路由"""
import os
import json
from aiohttp import web

from src.utils.logging import logger
from src.server.state import state


async def set_audiotype(request):
    """設定音訊型別"""
    try:
        params = await request.json()
        sessionid = params.get('sessionid', 0)
        state.avatar_streams[sessionid].set_custom_state(params['audiotype'], params['reinit'])

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


async def record(request):
    """處理錄製請求"""
    try:
        params = await request.json()
        logger.info(f'[錄製API] 收到請求: {params}')

        sessionid = params.get('sessionid', 0)
        logger.info(f'[錄製API] sessionid={sessionid}')
        
        if sessionid not in state.avatar_streams:
            logger.error(f'[錄製API] 錄製失敗: sessionid {sessionid} 不存在')
            logger.error(f'[錄製API] 當前可用的 sessionid: {list(state.avatar_streams.keys())}')
            return web.Response(
                content_type="application/json",
                text=json.dumps(
                    {"code": -1, "msg": f"sessionid {sessionid} not found"}
                ),
                status=404
            )
        
        if state.avatar_streams[sessionid] is None:
            logger.error(f'[錄製API] 錄製失敗: sessionid {sessionid} 的 avatar_stream 為 None')
            return web.Response(
                content_type="application/json",
                text=json.dumps(
                    {"code": -1, "msg": "avatar stream not initialized"}
                ),
                status=500
            )
        
        avatar_stream = state.avatar_streams[sessionid]
        logger.info(f'[錄製API] 找到 avatar_stream: {type(avatar_stream).__name__}')
        logger.info(f'[錄製API] avatar_stream.recording 狀態: {avatar_stream.recording}')
        logger.info(f'[錄製API] avatar_stream 影片尺寸: width={avatar_stream.width}, height={avatar_stream.height}')
        
        if params['type'] == 'start_record':
            logger.info(f'[錄製API] 開始錄製 sessionid={sessionid}')
            avatar_stream.start_recording()
            logger.info(f'[錄製API] start_recording 呼叫完成，當前 recording 狀態: {avatar_stream.recording}')
            return web.Response(
                content_type="application/json",
                text=json.dumps(
                    {"code": 0, "msg": "ok"}
                ),
            )
        elif params['type'] == 'end_record':
            logger.info(f'[錄製API] 停止錄製 sessionid={sessionid}')
            avatar_stream.stop_recording()
            logger.info(f'[錄製API] stop_recording 呼叫完成')
            
            response_data = {"code": 0, "msg": "ok"}
            if avatar_stream.current_record_file:
                filename = os.path.basename(avatar_stream.current_record_file)
                response_data['filename'] = filename
                response_data['filepath'] = avatar_stream.current_record_file
                logger.info(f'[錄製API] 返回檔案資訊: {filename}')
            
            return web.Response(
                content_type="application/json",
                text=json.dumps(response_data),
            )
    except Exception as e:
        logger.exception('[錄製API] 錄製異常:')
        return web.Response(
            content_type="application/json",
            text=json.dumps(
                {"code": -1, "msg": str(e)}
            ),
            status=500
        )


async def download_record(request):
    """下載錄製的影片檔案"""
    try:
        filename = request.match_info.get('filename', '')
        if not filename:
            return web.Response(text='檔名不能為空', status=400)
        
        # 只允許下載 records 目錄下的檔案
        if '..' in filename or '/' in filename or '\\' in filename:
            return web.Response(text='非法檔名', status=400)
        
        filepath = f'data/records/{filename}'
        
        if not os.path.exists(filepath):
            logger.warning(f'[下載] 檔案不存在: {filepath}')
            return web.Response(text='檔案不存在', status=404)
        
        logger.info(f'[下載] 開始下載檔案: {filepath}')
        
        return web.FileResponse(
            path=filepath,
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"'
            }
        )
    except Exception as e:
        logger.exception('[下載] 下載異常:')
        return web.Response(text=f'下載失敗: {str(e)}', status=500)
