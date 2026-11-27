# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""音訊相關路由"""
import json
from uuid import uuid4

from aiohttp import web
import asyncio

from nova_contracts.llm import ContextCapacityExceeded, Question, ReplyRequest, TurnCommit
from nova_contracts.stt import TranscriptionOptions
from nova_llm.config_section import reply_rules
from nova_core.server.reply_streaming.llm_reply import conversation_session, stream_reply
from nova_core.server.reply_streaming.speech import ReplySpeech
from nova_core.utils.logging import logger
from nova_core.server.state import state
from nova_core.vad import preprocess_pcm
from nova_core.vad.audio import AudioTooLongError, decode_audio

# Uploaded clips are decoded on worker threads, and only up to these lengths.
MAX_ASR_AUDIO_SECONDS = 60.0
ASR_SAMPLE_RATE = 16000


def _json(payload: dict, status: int = 200) -> web.Response:
    return web.Response(content_type="application/json", text=json.dumps(payload), status=status)


def _session_not_found(sessionid: int) -> web.Response:
    return _json({"code": -1, "msg": f"sessionid {sessionid} not found"}, status=404)


async def humanaudio(request):
    """處理音訊檔案上傳"""
    try:
        form = await request.post()
        sessionid = int(form.get('sessionid', 0))
        avatar_stream = state.avatar_streams.get(sessionid)
        if avatar_stream is None:
            return _session_not_found(sessionid)
        fileobj = form["file"]
        filebytes = fileobj.file.read()
        # Decoding, resampling and waiting for queue space all block.
        await asyncio.to_thread(avatar_stream.put_audio_file, filebytes)
        return _json({"code": 0, "msg": "ok"})
    except AudioTooLongError as e:
        return _json({"code": -1, "msg": str(e)}, status=413)
    except Exception as e:
        logger.exception('exception:')
        return _json({"code": -1, "msg": str(e)})


async def asr(request):
    """ASR 語音識別介面：將音訊轉換為文本，然後呼叫 LLM 進行對話"""
    try:
        form = await request.post()
        sessionid = int(form.get('sessionid', 0))
        avatar_stream = state.avatar_streams.get(sessionid)
        if avatar_stream is None:
            return _session_not_found(sessionid)
        fileobj = form["file"]
        filebytes = fileobj.file.read()

        # Decoded once, at most MAX_ASR_AUDIO_SECONDS; VAD and the recognizer
        # only ever see this PCM (as WAV), never the uploaded container.
        try:
            pcm = await asyncio.to_thread(
                decode_audio, filebytes, ASR_SAMPLE_RATE, MAX_ASR_AUDIO_SECONDS)
        except AudioTooLongError as e:
            return _json({"code": -1, "msg": str(e)}, status=413)
        except ValueError:
            return _json({"code": -1, "msg": "無法讀取音訊檔案"}, status=400)

        # ASR/LLM 呼叫在同一流程中，失敗時返回可讀錯誤
        try:
            asr_config = state.config.asr if state.config else None
            vad_config = getattr(state.config, 'vad', None) if state.config else None

            # 先過 VAD：全是靜音/噪聲就不用麻煩 ASR，有語音則裁掉前後靜音
            vad_result = await asyncio.to_thread(
                preprocess_pcm, pcm, ASR_SAMPLE_RATE, vad_config, state.config
            )
            if not vad_result.has_speech:
                return _json({"code": -1, "msg": "未檢測到語音內容", "vad": vad_result.engine})
            filebytes = vad_result.audio_bytes

            if state.stt is None:
                return _json({"code": -1, "msg": "語音辨識服務尚未就緒"}, status=503)
            # The voice sessions' STT service, so both share one loaded recognizer;
            # the per-request language keeps that recognizer unchanged.
            options = TranscriptionOptions(language=asr_config.language if asr_config else "zh")

            logger.info(f'[ASR] 開始識別音訊，sessionid={sessionid}')
            result = await asyncio.to_thread(state.stt.transcribe, filebytes, options)
            text = result.text.strip()

            if not text:
                return _json({"code": -1, "msg": "未識別到語音內容"})

            logger.info(f'[ASR] 識別結果: {text}')

            if state.llm is None:
                return _json({"code": -1, "msg": "回答模型服務尚未就緒"}, status=503)
            llm_text = await asyncio.to_thread(_answer, sessionid, avatar_stream, text)
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


def _answer(sessionid: int, avatar_stream, text: str) -> str:
    """Answer one recognized question with whole sentences; history keeps what was said."""
    config = getattr(avatar_stream, "config", None) or state.config
    published = config if getattr(config, "conversation_snapshot", False) else state.config or config
    turn_id = uuid4().hex
    request = ReplyRequest(
        session=conversation_session(config, published, sessionid),
        question=Question(text=text),
        rules=reply_rules(config if getattr(config, "profile_id", "") else published),
        turn_id=turn_id,
        stream_speech=True,
    )
    speech = ReplySpeech(avatar_stream, {}, settings=getattr(state.config, "reply_streaming", None))
    try:
        answer = stream_reply(state.llm, request, speech=speech).text
    except ContextCapacityExceeded:
        raise
    except Exception:
        state.llm.commit_turn(TurnCommit(session_id=sessionid, turn_id=turn_id,
                                         terminal_reason="llm_error"))
        raise
    state.llm.commit_turn(TurnCommit(session_id=sessionid, turn_id=turn_id,
                                     assistant_text=answer, terminal_reason="completed"))
    return answer
