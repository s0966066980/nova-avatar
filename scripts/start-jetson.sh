#!/usr/bin/env bash
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
export PATH="$HOME/.local/bin:$PATH"
# GPU inference shares the Orin CPU with RTP and browser rendering. Avoid
# large CPU worker pools for small FFT/BLAS/resize jobs in each mouth batch.
export OMP_NUM_THREADS="${NOVA_AVATAR_CPU_THREADS:-1}"
export OPENBLAS_NUM_THREADS="$OMP_NUM_THREADS"
export MKL_NUM_THREADS="$OMP_NUM_THREADS"
export OPENCV_FOR_THREADS_NUM="$OMP_NUM_THREADS"
# Start a prepared native RAGFlow deployment with the normal Jetson profile.
export NOVA_START_RAGFLOW="${NOVA_START_RAGFLOW:-auto}"
CONFIG_FILE="config/config_jetson.yaml"
MODE_FLAG=""
PROD_MODE=0
for arg in "$@"; do
    case "$arg" in
        --help|-h)
            echo "Usage: bash scripts/start-jetson.sh [--prod | --server] [--read-aloud | --realtime | config/file.yaml]"
            echo "Default: portrait 720p (720x1280) accelerated conversation and read-aloud, with saved dialogue preferences."
            echo "--prod, --server: single-origin :8010 production mode serving web/dist without Vite :3000."
            echo "--read-aloud: portrait 720p accelerated fixed read-aloud; no LLM or microphone processing."
            echo "--realtime: portrait 720p accelerated read-aloud; approximate mouth decoder; no LLM or microphone processing."
            exit 0
            ;;
        --prod|--server)
            PROD_MODE=1
            ;;
        --realtime|--read-aloud)
            MODE_FLAG="$arg"
            ;;
        *)
            CONFIG_FILE="$arg"
            ;;
    esac
done
if [[ "$MODE_FLAG" == "" && "$CONFIG_FILE" == config/config_jetson.yaml ]]; then
    echo "Jetson 一般模式：保留控制台已保存的對話、數位人呈現方式與畫質設定。"
fi
if [[ "$MODE_FLAG" == --realtime || "$MODE_FLAG" == --read-aloud ]]; then
    OUTPUT_HEIGHT=1280
    if [[ "$MODE_FLAG" == --read-aloud ]]; then
        CONFIG_FILE=config/config_jetson_read_aloud.yaml
        OUTPUT_HEIGHT=1280
    else
        CONFIG_FILE=config/config_jetson_realtime.yaml
    fi
    export NOVA_AVATAR_RUNTIME_OVERRIDES_ENABLED=0
    export NOVA_START_RAGFLOW=0
    echo "加速朗讀：輸出高度 ${OUTPUT_HEIGHT}、TensorRT UNet、輕量嘴型解碼；不載入 LLM、VAD 或 ASR。"
    echo "輕量解碼會略柔化牙齒與唇部細節；目前只測試朗讀模式。"
fi
uv run python scripts/check-cuda.py
if [[ "$PROD_MODE" -eq 1 ]]; then
    exec bash scripts/start-server.sh "$CONFIG_FILE"
fi
exec bash scripts/start-all.sh "$CONFIG_FILE"
