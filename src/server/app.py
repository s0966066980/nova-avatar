# Derived from Kedreamix/Linly-Talker-Stream.
# Copyright [Linly-talker-stream@kedreamix].
# Licensed under the Apache License, Version 2.0.
#
# Modified by HongXian0903, 2026.
# See LICENSE and NOTICE for details.
# Based on LiveTalking (C) 2024 LiveTalking@lipku https://github.com/lipku/LiveTalking (Apache-2.0).

"""主啟動檔案"""
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json
import time
import argparse
from threading import Thread
import torch.multiprocessing as mp

from src.utils.logging import logger
from src.config.loader import load_config
from src.avatars.factory import prepare_avatar_model
from src.server.state import state
from src.server.server import FrontendNotBuilt, create_app, require_frontend, run_server


EDGE_PREWARM_MAX_ATTEMPTS = 3
EDGE_PREWARM_RETRY_SECONDS = 1.0


def _start_edge_tts_prewarm(config) -> Thread | None:
    """Overlap Edge's process-cold network setup with local model loading."""
    if (not getattr(getattr(config, "app", None), "prewarm", True)
            or str(getattr(config.tts, "type", "")).strip().lower() != "edgetts"):
        return None
    from src.tts.engines.edge import prewarm_edge_tts

    voice = str(getattr(config.tts, "ref_file", "") or "").strip()
    def warm():
        for attempt in range(EDGE_PREWARM_MAX_ATTEMPTS):
            worker.prewarm_ready = prewarm_edge_tts(voice, decode_pcm=True,
                keep_connection=bool(getattr(config.tts, "edge_connection_reuse", False)))
            if worker.prewarm_ready:
                return
            if attempt + 1 < EDGE_PREWARM_MAX_ATTEMPTS:
                time.sleep(EDGE_PREWARM_RETRY_SECONDS * (attempt + 1))

    worker = Thread(
        target=warm,
        name="edge-tts-prewarm",
        daemon=True,
    )
    worker.prewarm_ready = False
    worker.start()
    return worker


def _await_edge_tts_prewarm(worker: Thread | None) -> bool:
    if worker is None:
        return True
    from src.tts.engines.edge import EDGE_WARMUP_TIMEOUT_SECONDS

    worker.join(timeout=EDGE_WARMUP_TIMEOUT_SECONDS * EDGE_PREWARM_MAX_ATTEMPTS + EDGE_PREWARM_RETRY_SECONDS * 3 + 1.0)
    if worker.is_alive():
        logger.warning("Edge TTS prewarm did not finish before server startup")
        return False
    return bool(getattr(worker, "prewarm_ready", False))


def main():
    """主啟動函式"""
    # 設定 multiprocessing 啟動方式
    try:
        mp.set_start_method('spawn')
    except RuntimeError:
        pass
    
    # 解析命令列引數
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--config', 
        type=str, 
        default="config/config.yaml",
        help="path to config file (e.g., config/config.yaml)"
    )
    args = parser.parse_args()
    # Fail before loading models: without web/dist there is no console or stage.
    try:
        frontend_dir = require_frontend()
    except FrontendNotBuilt as exc:
        raise SystemExit(str(exc)) from None
    
    # 載入配置
    state.config_path = args.config
    state.config = load_config(config_file=args.config)
    logger.info(f"已載入配置: {state.config}")
    from src.scene.service import SceneError, scene_service

    try:
        scene_service.select(getattr(state.config.stage, "background_id", ""))
    except SceneError as exc:
        logger.warning("未能載入已選舞台背景：%s", exc)
        state.config.stage.background_id = ""
    edge_tts_prewarm = _start_edge_tts_prewarm(state.config)

    # The llama.cpp child belongs to this backend when ensure_server starts it;
    # register termination cleanup before model loading so even Ctrl-C during
    # startup cannot leave the GPU process behind.
    from src.llm.llamacpp import install_shutdown_handlers

    install_shutdown_handlers()
    
    # 載入自定義影片配置
    state.config.customopt = []
    if state.config.custom_video.config_path:
        with open(state.config.custom_video.config_path, 'r') as file:
            state.config.customopt = json.load(file)
    
    # 數字人可在設定裡切換；啟動時只預載「已選且素材齊全」的角色
    from src.avatars.catalog import avatar_bootable

    engine = state.config.model.type
    avatar_id = state.config.model.avatar_id
    bootable, reason = avatar_bootable(engine, avatar_id)
    if bootable:
        logger.info(f"正在載入數字人: {engine} / {avatar_id}")
        try:
            state.model, state.avatar = prepare_avatar_model(state.config)
            state.model_ready = True
            logger.info("數字人載入完成")
        except Exception:
            logger.exception("啟動時載入數字人失敗，服務仍會啟動，請到設定中重新選擇")
            state.model = None
            state.avatar = None
            state.model_ready = False
    else:
        logger.warning(f"啟動時不預載數字人：{reason}。請開啟設定選擇引擎與角色。")
        state.model_ready = False
    
    # 若當前選的是 llama.cpp，先把 llama-server 拉起來，避免對話 Connection refused
    if getattr(state.config.llm, "provider", "") == "llamacpp":
        try:
            from src.llm.llamacpp import ensure_server

            logger.info("正在啟動 llama-server: %s", state.config.llm.model)
            state.config.llm.base_url = ensure_server(
                state.config.llm.model,
                extra_dir=getattr(state.config.llm, "llamacpp_dir", "") or "",
                host=getattr(state.config.llm, "llamacpp_host", "127.0.0.1") or "127.0.0.1",
                port=int(getattr(state.config.llm, "llamacpp_port", 8080) or 8080),
                ctx=int(getattr(state.config.llm, "llamacpp_ctx", 8192) or 8192),
                threads=int(getattr(state.config.llm, "llamacpp_threads", 0) or 0),
            )
            logger.info("llama-server 已就緒: %s", state.config.llm.base_url)
        except Exception:
            logger.exception("啟動 llama-server 失敗，對話時會再試一次")

    tts_type = str(getattr(state.config.tts, "type", "")).strip().lower()
    from src.tts.cosyvoice_runtime import is_cosyvoice_engine

    if is_cosyvoice_engine(tts_type):
        try:
            from src.tts.cosyvoice_runtime import (
                cosyvoice_family,
                ensure_server,
                family_label,
                parse_server_url,
            )

            family = cosyvoice_family(tts_type)
            host, port = parse_server_url(getattr(state.config.tts, "tts_server", "") or "")
            label = family_label(family)
            logger.info("正在啟動 %s: %s", label, getattr(state.config.tts, "model", "") or label)
            state.config.tts.tts_server = ensure_server(
                model_dir=getattr(state.config.tts, "model", "") or "",
                family=family,
                host=host,
                port=port,
            )
            logger.info("%s 已就緒: %s", label, state.config.tts.tts_server)
        except Exception:
            logger.exception("啟動 CosyVoice 失敗，請到設定重新套用 TTS")

    # Orin's disposable prompt/PCM warmups also apply to x86. Prime actual
    # recognizer inference here, so listening never spends its first turn on it.
    enabled = state.config.app.prewarm
    llm_ready = speech_ready = None
    if enabled:
        from src.llm.prewarm import prewarm_local_llm
        from src.asr.prewarm import prewarm_speech_input

        if state.config.llm.provider == "llamacpp":
            llm_ready = prewarm_local_llm(state.config)
        if state.config.vad.enabled:
            speech_ready = prewarm_speech_input(state.config)
    edge_ready = _await_edge_tts_prewarm(edge_tts_prewarm)
    state.prewarm_status = {
        "enabled": enabled,
        "avatar": (state.model_ready if enabled and state.config.model.type
                   in {"musetalk", "wav2lip", "ultralight"} else None),
        "edge_tts": edge_ready if edge_tts_prewarm is not None else None,
        "local_llm": llm_ready,
        "speech_input": speech_ready,
    }
    logger.info("Startup prewarm: %s", state.prewarm_status)

    # 建立並執行應用
    app = create_app(frontend_dir=frontend_dir)
    run_server(app, state.config)


if __name__ == '__main__':
    main()
