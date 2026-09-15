# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""音訊相關路由"""
import json
from aiohttp import web
import asyncio

from src.llm.service import llm_response
from src.utils.logging import logger
from src.server.state import state


async def humanaudio(request):
    """處理音訊檔案上傳"""
    try:
        form = await request.post()
        sessionid = int(form.get('sessionid', 0))
        fileobj = form["file"]
        filename = fileobj.filename
        filebytes = fileobj.file.read()
        state.avatar_streams[sessionid].put_audio_file(filebytes)

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


async def asr(request):
    """ASR 語音識別介面：將音訊轉換為文本，然後呼叫 LLM 進行對話"""
    try:
        form = await request.post()
        sessionid = int(form.get('sessionid', 0))
        fileobj = form["file"]
        filebytes = fileobj.file.read()

        # ASR/LLM 呼叫在同一流程中，失敗時返回可讀錯誤
        from src.asr import get_asr_engine
        from src.vad import preprocess_audio_bytes

        try:
            asr_config = state.config.asr if state.config else None
            vad_config = getattr(state.config, 'vad', None) if state.config else None

            # 先過 VAD：全是靜音/噪聲就不用麻煩 ASR，有語音則裁掉前後靜音
            loop = asyncio.get_event_loop()
            vad_result = await loop.run_in_executor(
                None, preprocess_audio_bytes, filebytes, vad_config, state.config
            )
            if not vad_result.has_speech:
                return web.Response(
                    content_type="application/json",
                    text=json.dumps(
                        {"code": -1, "msg": "未檢測到語音內容", "vad": vad_result.engine}
                    ),
                )
            filebytes = vad_result.audio_bytes
            
            asr_engine = get_asr_engine(
                asr_type=asr_config.type if asr_config else "whisper",
                model_size=asr_config.model_size if asr_config else "base",
                device=asr_config.device if asr_config else "auto",
            )
            
            language = asr_config.language if asr_config else "zh"
            asr_engine.set_language(language)
            
            logger.info(f'[ASR] 開始識別音訊，sessionid={sessionid}')
            result = await loop.run_in_executor(None, asr_engine.transcribe, filebytes)
            text = result.get("text", "").strip()
            
            if not text:
                return web.Response(
                    content_type="application/json",
                    text=json.dumps(
                        {"code": -1, "msg": "未識別到語音內容"}
                    ),
                )
            
            logger.info(f'[ASR] 識別結果: {text}')
            
            llm_config = state.config.llm if state.config else None
            logger.info(f'[ASR] LLM 配置: {llm_config}')
            avatar_stream = state.avatar_streams.get(sessionid)
            if avatar_stream is None:
                return web.Response(
                    content_type="application/json",
                    text=json.dumps(
                        {"code": -1, "msg": f"sessionid {sessionid} not found"}
                    ),
                    status=404
                )

            llm_text = await loop.run_in_executor(
                None,
                llm_response,
                text,
                avatar_stream,
                llm_config.api_key if llm_config else None,
                llm_config.base_url if llm_config else "https://dashscope.aliyuncs.com/compatible-mode/v1",
                llm_config.model if llm_config else "qwen-plus",
            )
            logger.info(f'[ASR] LLM 回覆: {llm_text}')
            
            avatar_stream.put_msg_txt(llm_text)
            
            return web.Response(
                content_type="application/json",
                text=json.dumps(
                    {"code": 0, "msg": "ok", "text": text, "response": llm_text}
                ),
            )
            
        except Exception as e:
            logger.exception('[ASR] 語音識別失敗:')
            return web.Response(
                content_type="application/json",
                text=json.dumps(
                    {"code": -1, "msg": f"語音識別失敗: {str(e)}"}
                ),
            )
            
    except Exception as e:
        logger.exception('[ASR] ASR 介面異常:')
        return web.Response(
            content_type="application/json",
            text=json.dumps(
                {"code": -1, "msg": str(e)}
            ),
        )
