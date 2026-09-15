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
import argparse
from threading import Thread
import torch.multiprocessing as mp

from src.utils.logging import logger
from src.config.loader import load_config
from src.avatars.factory import prepare_avatar_model
from src.server.state import state
from src.server.server import create_app, run_server


def _start_edge_tts_prewarm(config) -> Thread | None:
    """Overlap Edge's process-cold network setup with local model loading."""
    if str(getattr(config.tts, "type", "")).strip().lower() != "edgetts":
        return None
    from src.tts.engines.edge import prewarm_edge_tts

    voice = str(getattr(config.tts, "ref_file", "") or "").strip()
    worker = Thread(
        target=prewarm_edge_tts,
        args=(voice,),
        name="edge-tts-prewarm",
        daemon=True,
    )
    worker.start()
    return worker


def _await_edge_tts_prewarm(worker: Thread | None) -> None:
    if worker is None:
        return
    from src.tts.engines.edge import EDGE_WARMUP_TIMEOUT_SECONDS

    worker.join(timeout=EDGE_WARMUP_TIMEOUT_SECONDS + 1.0)
    if worker.is_alive():
        logger.warning("Edge TTS prewarm did not finish before server startup")


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
    
    # 載入配置
    state.config_path = args.config
    state.config = load_config(config_file=args.config)
    logger.info(f"已載入配置: {state.config}")
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
    if tts_type in {"cosyvoice", "fun-cosyvoice3"}:
        try:
            from src.tts.cosyvoice_runtime import (
                cosyvoice_family,
                ensure_server,
                parse_server_url,
            )

            family = cosyvoice_family(tts_type)
            host, port = parse_server_url(getattr(state.config.tts, "tts_server", "") or "")
            label = "Fun-CosyVoice 3.0" if family == "cosyvoice3" else "CosyVoice2-0.5B"
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

    # Do not announce readiness while the first Edge connection is still cold.
    _await_edge_tts_prewarm(edge_tts_prewarm)

    # 建立並執行應用
    app = create_app()
    run_server(app, state.config)


if __name__ == '__main__':
    main()
