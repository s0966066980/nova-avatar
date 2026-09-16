# Derived from Kedreamix/Linly-Talker-Stream.
# Copyright [Linly-talker-stream@kedreamix].
# Licensed under the Apache License, Version 2.0.
#
# Modified by HongXian0903, 2026.
# See LICENSE and NOTICE for details.
# Based on LiveTalking (C) 2024 LiveTalking@lipku https://github.com/lipku/LiveTalking (Apache-2.0).

"""伺服器啟動和配置"""
import asyncio
from aiohttp import web
import aiohttp_cors

from src.utils.logging import logger
from src.server.state import state
from src.server import routes
from src.llm.llamacpp import shutdown_llama_server
from src.tts.cosyvoice_runtime import shutdown_cosyvoice_server


async def on_shutdown(app):
    """伺服器關閉時的清理操作"""
    coros = [pc.close() for pc in state.pcs]
    await asyncio.gather(*coros)
    state.pcs.clear()
    shutdown_llama_server()
    shutdown_cosyvoice_server()


def create_app():
    """建立並配置 aiohttp 應用"""
    # 單獨設定較大的請求體上限，方便上傳音影片
    app = web.Application(client_max_size=1024**2*100)
    app.on_shutdown.append(on_shutdown)
    
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
    app.router.add_post("/api/ragflow/test", routes.test_ragflow_retrieval)
    app.router.add_get("/api/llm/models", routes.list_llm_models)
    app.router.add_post("/api/llm/model", routes.set_llm_model)
    app.router.add_get("/api/llm/rules", routes.get_llm_rules)
    app.router.add_put("/api/llm/rules", routes.set_llm_rules)
    app.router.add_post("/api/avatar", routes.set_avatar)
    app.router.add_post("/api/avatar/quality", routes.set_mouth_quality)
    app.router.add_get("/api/vad", routes.get_vad_settings)
    app.router.add_post("/api/vad", routes.set_vad_settings)
    app.router.add_get("/api/speech", routes.get_speech_settings)
    app.router.add_post("/api/speech/stt", routes.set_stt_settings)
    app.router.add_post("/api/speech/tts", routes.set_tts_settings)
    app.router.add_post("/api/speech/path-picker", routes.pick_speech_path)
    app.router.add_get("/api/stage", routes.get_stage_settings)
    app.router.add_post("/api/stage", routes.set_stage_settings)
    app.router.add_get("/api/avatars/{avatar_id}/preview", routes.avatar_preview)
    app.router.add_post("/api/avatars/import", routes.import_avatar)
    app.router.add_get("/api/avatars/import/{job_id}", routes.import_avatar_status)
    app.router.add_get("/api/voice-tests", routes.list_voice_tests)
    app.router.add_post("/api/voice-tests/run", routes.run_voice_test)
    app.router.add_delete("/api/voice-tests", routes.clear_voice_tests)
    # 前端靜態資源託管
    app.router.add_static('/', path='web')
    
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
    logger.info('✅ 服務已就緒，可以接受連線')
    
    def _run():
        # 獨立事件迴圈，避免與外部執行緒衝突
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        runner = web.AppRunner(app)
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
        loop.run_forever()
    
    _run()
