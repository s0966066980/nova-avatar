# Derived from Kedreamix/Linly-Talker-Stream.
# Copyright [Linly-talker-stream@kedreamix].
# Licensed under the Apache License, Version 2.0.
#
# Modified by HongXian0903, 2026.
# See LICENSE and NOTICE for details.
# Based on LiveTalking (C) 2024 LiveTalking@lipku https://github.com/lipku/LiveTalking (Apache-2.0).

"""伺服器啟動和配置"""
import asyncio
import os
import signal
import threading

from pathlib import Path
from aiohttp import web
import aiohttp_cors

from src.utils.logging import logger
from src.server.state import state
from src.server import routes
from src.llm.llamacpp import shutdown_llama_server
from src.tts.cosyvoice_runtime import shutdown_cosyvoice_server
from src.scene.service import scene_service
from src.profiles.coordinator import initialize_roles
from src.server.routes.profiles import register_profile_routes


# Upper bound for an orderly stop after SIGTERM/SIGINT. Closing WebRTC peers
# lets the per-session render, inference and TTS threads see their quit events;
# if anything still holds the process after this, it exits anyway.
SHUTDOWN_DEADLINE_SECONDS = 15.0
# How long aiohttp waits for open HTTP connections while cleaning up.
HTTP_SHUTDOWN_TIMEOUT_SECONDS = 5.0


@web.middleware
async def profile_settings_guard(request, handler):
    roles = getattr(state, "roles", None)
    if roles and getattr(roles, "profiles_applied", False) and request.method in {"POST", "PUT"} and request.path in {
        "/api/llm/model", "/api/llm/rules", "/api/llm/behavior", "/api/ragflow/settings",
    }:
        return web.json_response({"code": -1, "msg": "請至數位人設定檔修改模型、規則與知識範圍並套用"}, status=409)
    if roles and roles.enabled and request.path == "/humanaudio" and request.method == "POST":
        return web.json_response({"code": -1, "msg": "角色組合請使用即時麥克風或文字對話"}, status=409)
    if roles and roles.enabled and request.method in {"POST", "PUT"} and request.path in {
        "/api/llm/model", "/api/llm/rules", "/api/llm/behavior", "/api/avatar", "/api/avatar/quality",
        "/api/speech/tts", "/api/ragflow/settings",
    }:
        return web.json_response({"code": -1, "msg": "角色組合啟用中，請至數位人設定檔修改並套用"}, status=409)
    return await handler(request)


async def on_shutdown(app):
    """伺服器關閉時的清理操作"""
    state.shutting_down = True
    if state.roles is not None:
        await state.roles.close()
    coros = [pc.close() for pc in state.pcs]
    await asyncio.gather(*coros, return_exceptions=True)
    state.pcs.clear()
    # The peers' "closed" callbacks may not get a turn before the loop stops.
    for session in list(state.voice_sessions.values()):
        try:
            await session.close()
        except Exception:
            logger.exception("關閉語音工作階段失敗")
    from src.tts.engines.edge import shutdown_edge_tts
    await asyncio.to_thread(shutdown_edge_tts)
    shutdown_llama_server()
    shutdown_cosyvoice_server()
    scene_service.close()


def create_app():
    """建立並配置 aiohttp 應用"""
    state.shutting_down = False
    # 單獨設定較大的請求體上限，方便上傳音影片
    # Leave space for multipart headers around the 100 MB background asset.
    app = web.Application(client_max_size=1024**2*101, middlewares=[profile_settings_guard])
    from src.server.routes.attachments import register as register_attachments
    register_attachments(app)
    from src.server import conversations
    app.router.add_get('/api/conversations', conversations.list_conversations)
    app.router.add_post('/api/conversations/defaults', conversations.save_defaults)
    app.router.add_post(r'/api/conversations/{sessionid:\d+}', conversations.update_conversation)
    app.router.add_post(r'/api/conversations/{sessionid:\d+}/clear', conversations.clear_conversation)
    app.on_shutdown.append(on_shutdown)
    async def prepare_roles(app):
        if state.config is not None and state.config_path:
            from src.server.deferred_settings import apply_pending
            await apply_pending()
            await initialize_roles(state)
    app.on_startup.append(prepare_roles)
    register_profile_routes(app)
    
    # 路由集中註冊，避免分散難維護
    app.router.add_post("/offer", routes.offer)
    app.router.add_post("/human", routes.human)
    app.router.add_post("/humanaudio", routes.humanaudio)
    app.router.add_post("/asr", routes.asr)
    app.router.add_post("/set_audiotype", routes.set_audiotype)
    app.router.add_post("/record", routes.record)
    app.router.add_post("/interrupt_talk", routes.interrupt_talk)
    app.router.add_post("/is_speaking", routes.is_speaking)
    app.router.add_post("/clear_history", routes.clear_history)
    app.router.add_get("/health", routes.health_check)
    app.router.add_get("/download/{filename}", routes.download_record)
    app.router.add_get("/api/settings", routes.get_settings)
    app.router.add_get("/api/ragflow/settings", routes.get_ragflow_settings)
    app.router.add_put("/api/ragflow/settings", routes.put_ragflow_settings)
    app.router.add_get("/api/ragflow/datasets", routes.list_ragflow_datasets)
    app.router.add_get("/api/ragflow/status", routes.ragflow_status)
    app.router.add_get("/api/ragflow/datasets/{dataset_id}/documents", routes.list_ragflow_documents)
    app.router.add_post("/api/ragflow/test", routes.test_ragflow_retrieval)
    app.router.add_get("/api/llm/models", routes.list_llm_models)
    app.router.add_post("/api/llm/model", routes.set_llm_model)
    app.router.add_put("/api/llm/behavior", routes.set_llm_behavior)
    app.router.add_get("/api/llm/rules", routes.get_llm_rules)
    app.router.add_put("/api/llm/rules", routes.set_llm_rules)
    app.router.add_post("/api/avatar", routes.set_avatar)
    app.router.add_post("/api/avatar/quality", routes.set_mouth_quality)
    app.router.add_post("/api/avatar/output", routes.set_video_output)
    app.router.add_get("/api/vad", routes.get_vad_settings)
    app.router.add_post("/api/vad", routes.set_vad_settings)
    app.router.add_get("/api/speech", routes.get_speech_settings)
    app.router.add_post("/api/speech/stt", routes.set_stt_settings)
    app.router.add_post("/api/speech/tts", routes.set_tts_settings)
    app.router.add_post("/api/speech/path-picker", routes.pick_speech_path)
    app.router.add_get("/api/stage", routes.get_stage_settings)
    app.router.add_post("/api/stage", routes.set_stage_settings)
    app.router.add_get("/api/backgrounds", routes.get_backgrounds)
    app.router.add_post("/api/backgrounds", routes.upload_background)
    app.router.add_post("/api/background", routes.select_background)
    app.router.add_get("/api/backgrounds/{background_id}/preview", routes.background_preview)
    app.router.add_delete("/api/backgrounds/{background_id}", routes.delete_background)
    app.router.add_get("/api/backgrounds/deleted", routes.archived_backgrounds)
    app.router.add_post("/api/backgrounds/deleted/{archive_name}/restore", routes.restore_archived_background)
    app.router.add_delete("/api/avatars/{avatar_id}", routes.delete_avatar)
    app.router.add_get("/api/avatars/deleted", routes.archived_avatars)
    app.router.add_post("/api/avatars/deleted/{archive_name}/restore", routes.restore_archived_avatar)
    app.router.add_delete("/api/avatars/deleted/{archive_name}", routes.delete_archived_avatar_permanently)
    app.router.add_get("/api/avatars/{avatar_id}/preview", routes.avatar_preview)
    app.router.add_get("/api/avatars/{avatar_id}/scene-preview", routes.avatar_scene_preview)
    app.router.add_post("/api/avatars/import", routes.import_avatar)
    app.router.add_get("/api/avatars/import/{job_id}", routes.import_avatar_status)
    app.router.add_get("/api/voice-tests", routes.list_voice_tests)
    app.router.add_post("/api/voice-tests/run", routes.run_voice_test)
    app.router.add_delete("/api/voice-tests", routes.clear_voice_tests)
    # 前端靜態資源託管
    frontend = Path('web/dist')
    app.router.add_static('/', path=frontend if (frontend / 'index.html').is_file() else Path('web'))
    
    # 寬鬆 CORS 方便本地除錯和跨域訪問
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
        )
    })
    
    for route in list(app.router.routes()):
        cors.add(route)
    
    return app


def run_server(app, config):
    """執行伺服器"""
    # 相容新舊配置欄位
    use_ssl = getattr(config.app, 'ssl', False)
    if not use_ssl:
        use_ssl = hasattr(config.app, 'ssl_cert') and config.app.ssl_cert and \
                  hasattr(config.app, 'ssl_key') and config.app.ssl_key
    
    protocol = 'https' if use_ssl else 'http'
    listen_host = getattr(config.app, 'listenhost', '0.0.0.0')
    listen_port = config.app.listenport
    
    # 啟動資訊集中列印，便於排查配置問題
    logger.info('┌─────────────────────────────────────────────┐')
    logger.info('│  🚀 Nova Avatar 後端服務啟動中...           │')
    logger.info('├─────────────────────────────────────────────┤')
    logger.info(f'│  協議: {protocol.upper():<37} │')
    logger.info(f'│  監聽地址: {listen_host:<30} │')
    logger.info(f'│  監聽埠: {listen_port:<30} │')
    
    if protocol == 'http':
        logger.info('│                                             │')
        logger.info('│  ⚠️  HTTP 模式：瀏覽器錄音僅支援 localhost  │')
        logger.info('│  💡 遠端訪問需要在配置中啟用 ssl: true     │')
    else:
        logger.info(f'│  證書檔案: {config.app.ssl_cert:<28} │')
    
    logger.info('└─────────────────────────────────────────────┘')
    
    config.app.protocol = protocol
    
    # 標記可用，供健康檢查使用
    state.server_ready = True
    if getattr(state, "reply_prewarm_ready", True):
        logger.info('✅ 服務已就緒，可以接受連線')
    else:
        logger.warning('回覆預熱未完成；健康檢查未就緒，暫不接受對話')
    
    def _run():
        # 獨立事件迴圈，避免與外部執行緒衝突
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        runner = web.AppRunner(app, shutdown_timeout=HTTP_SHUTDOWN_TIMEOUT_SECONDS)
        loop.run_until_complete(runner.setup())
        
        if use_ssl:
            import ssl
            # 僅做服務端 TLS，不做客戶端校驗
            ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain(config.app.ssl_cert, config.app.ssl_key)
            site = web.TCPSite(runner, listen_host, listen_port, ssl_context=ssl_context)
            logger.info(f'✅ HTTPS 服務已啟動: https://{listen_host}:{listen_port}')
        else:
            site = web.TCPSite(runner, listen_host, listen_port)
            logger.info(f'✅ HTTP 服務已啟動: http://{listen_host}:{listen_port}')
        
        loop.run_until_complete(site.start())
        stop_signal = _install_stop_signals(loop)
        try:
            loop.run_forever()
        finally:
            _shutdown_loop(loop, runner)
        if stop_signal:
            raise SystemExit(128 + stop_signal[0])
    
    _run()


def _force_exit(code: int) -> None:
    """Exit now, but never leave owned model servers holding the GPU.

    os._exit skips atexit, so the owned servers are stopped here explicitly.
    """
    logger.error("強制結束程序 exit=%s", code)
    try:
        shutdown_llama_server()
        shutdown_cosyvoice_server()
    finally:
        os._exit(code)


def _install_stop_signals(loop) -> list:
    """Turn SIGTERM/SIGINT into an orderly stop of the serving loop.

    Signals that arrive while stopping are ignored: one Ctrl+C reaches the
    backend more than once (terminal, uv, start-all.sh cleanup), and treating a
    repeat as "force now" cut the orderly stop short. The deadline still bounds
    how long a stuck stop can take.
    """
    received: list = []

    def request_stop(signum: int) -> None:
        if received:
            logger.info("關閉進行中，忽略訊號 %s", signum)
            return
        received.append(signum)
        logger.info("收到關閉訊號 %s，正在關閉連線與服務", signum)
        deadline = threading.Timer(
            SHUTDOWN_DEADLINE_SECONDS, _force_exit, args=(128 + signum,)
        )
        deadline.daemon = True
        deadline.start()
        loop.stop()

    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, request_stop, signum)
    return received


def _shutdown_loop(loop, runner) -> None:
    """Run aiohttp's shutdown hooks, settle leftover tasks, then close the loop."""
    try:
        loop.run_until_complete(runner.cleanup())
    except Exception:
        logger.exception("伺服器關閉清理失敗")
    pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
    for task in pending:
        task.cancel()
    if pending:
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    shutdown_llama_server()
    loop.close()
