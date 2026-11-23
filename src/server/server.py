# Derived from Kedreamix/Linly-Talker-Stream.
# Copyright [Linly-talker-stream@kedreamix].
# Licensed under the Apache License, Version 2.0.
#
# Modified by HongXian0903, 2026.
# See LICENSE and NOTICE for details.
# Based on LiveTalking (C) 2024 LiveTalking@lipku https://github.com/lipku/LiveTalking (Apache-2.0).

"""伺服器啟動和配置"""
import asyncio
import signal
from pathlib import Path
from aiohttp import web
import aiohttp_cors

from src.utils.logging import logger
from src.utils.paths import get_project_root
from src.server.state import state
from src.server import routes
from src.server.admin_auth import admin_auth_middleware, register_admin_auth
from src.llm.llamacpp import shutdown_llama_server
from src.scene.service import scene_service
from src.weather import routing_clients


def _resolve_frontend_dir() -> Path:
    """解析前端靜態資源目錄，優先使用已建置的 web/dist。"""
    web_dir = get_project_root() / "web"
    dist_dir = web_dir / "dist"
    return dist_dir if (dist_dir / "index.html").is_file() else web_dir


async def on_shutdown(app):
    """伺服器關閉時的清理操作"""
    state.server_ready = False
    from src.server.routes.webrtc import close_sessions
    from src.tts.engines.edge import shutdown_edge_tts

    async def _close_edge_tts():
        await asyncio.to_thread(shutdown_edge_tts)

    for label, step in (
        ("WebRTC 會話", close_sessions),
        ("Edge TTS 連線池", _close_edge_tts),
    ):
        try:
            await step()
        except Exception:
            logger.exception("關閉 %s 時發生錯誤", label)

    for label, sync_step in (
        ("llama-server", shutdown_llama_server),
        ("舞台背景服務", scene_service.close),
        ("氣象路徑查詢客戶端", routing_clients.close),
    ):
        try:
            sync_step()
        except Exception:
            logger.exception("關閉 %s 時發生錯誤", label)


def create_app():
    """建立並配置 aiohttp 應用"""
    # 單獨設定較大的請求體上限，方便上傳音影片
    # Leave space for multipart headers around the 100 MB background asset.
    app = web.Application(
        client_max_size=1024**2*513,
        middlewares=[admin_auth_middleware],
    )
    register_admin_auth(app)
    from src.server.routes.presentation import register as register_presentation
    register_presentation(app)
    from src.server.routes.attachments import register as register_attachments
    register_attachments(app)
    app.on_shutdown.append(on_shutdown)
    
    # 路由集中註冊，避免分散難維護
    app.router.add_post("/offer", routes.offer)
    from src.server.routes.webrtc import release_session
    app.router.add_post("/api/sessions/release", release_session)
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
    from src.server.conversations import list_conversations, save_defaults, update_conversation, clear_conversation
    app.router.add_post(r'/api/conversations/{sessionid:\d+}/clear', clear_conversation)
    app.router.add_get('/api/conversations', list_conversations)
    app.router.add_post('/api/conversations/defaults', save_defaults)
    app.router.add_post('/api/conversations/{sessionid:\\d+}', update_conversation)
    app.router.add_get("/api/ragflow/settings", routes.get_ragflow_settings)
    app.router.add_put("/api/ragflow/settings", routes.put_ragflow_settings)
    app.router.add_get("/api/ragflow/datasets", routes.list_ragflow_datasets)
    app.router.add_post("/api/ragflow/test", routes.test_ragflow_retrieval)
    app.router.add_get("/api/weather/settings", routes.get_weather_settings)
    app.router.add_put("/api/weather/settings", routes.put_weather_settings)
    app.router.add_post("/api/weather/test", routes.test_weather_query)
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
    app.router.add_get("/api/tts/training", routes.get_tts_training_status)
    app.router.add_post("/api/tts/training/step", routes.run_tts_training_step)
    app.router.add_post("/api/tts/training/cancel", routes.cancel_tts_training)
    app.router.add_post("/api/tts/training/preview", routes.preview_tts_teacher_voice)
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
    frontend = _resolve_frontend_dir()

    async def serve_index(_request):
        index_file = frontend / "index.html"
        if not index_file.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(index_file)

    app.router.add_get("/", serve_index)
    app.router.add_static("/", path=frontend)
    
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
        runner = web.AppRunner(app)
        cleaned_up = False
        registered_signals: list[signal.Signals] = []

        async def _cleanup_once() -> None:
            nonlocal cleaned_up
            if cleaned_up:
                return
            cleaned_up = True
            await runner.cleanup()

        def _clear_signal_handlers() -> None:
            for sig in registered_signals:
                try:
                    loop.remove_signal_handler(sig)
                except (NotImplementedError, RuntimeError, ValueError):
                    pass
            registered_signals.clear()

        async def _serve() -> None:
            stop_event = asyncio.Event()
            stopping = False

            def _request_shutdown(signum: int) -> None:
                nonlocal stopping
                if not stopping:
                    stopping = True
                    state.server_ready = False
                    logger.info("收到關閉訊號 %s，正在優雅關閉伺服器...", signum)
                stop_event.set()

            await runner.setup()
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

            await site.start()
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, _request_shutdown, int(sig))
                    registered_signals.append(sig)
                except (NotImplementedError, RuntimeError):
                    pass

            try:
                await stop_event.wait()
            finally:
                _clear_signal_handlers()
                await _cleanup_once()

        try:
            loop.run_until_complete(_serve())
        except KeyboardInterrupt:
            logger.info("收到 KeyboardInterrupt，正在優雅關閉伺服器...")
        finally:
            _clear_signal_handlers()
            if not cleaned_up:
                loop.run_until_complete(_cleanup_once())
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()
                asyncio.set_event_loop(None)

    _run()
