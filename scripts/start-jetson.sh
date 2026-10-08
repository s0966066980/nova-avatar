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
CONFIG_FILE="${1:-config/config_jetson.yaml}"
if [[ "$CONFIG_FILE" == --help || "$CONFIG_FILE" == -h ]]; then
    echo "Usage: bash scripts/start-jetson.sh [--read-aloud | --realtime | config/file.yaml]"
    echo "Default: portrait 720p (720x1280) accelerated conversation and read-aloud, with saved dialogue preferences."
    echo "--read-aloud: portrait 720p accelerated fixed read-aloud; no LLM or microphone processing."
    echo "--realtime: portrait 720p accelerated read-aloud; approximate mouth decoder; no LLM or microphone processing."
    exit 0
fi
if [[ "$CONFIG_FILE" == config/config_jetson.yaml ]]; then
    echo "Jetson 一般模式：直式 720p（720×1280）、TensorRT UNet 與輕量嘴型解碼；保留已保存的對話設定。"
fi
if [[ "$CONFIG_FILE" == --realtime || "$CONFIG_FILE" == --read-aloud ]]; then
    OUTPUT_HEIGHT=1280
    if [[ "$CONFIG_FILE" == --read-aloud ]]; then
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
exec bash scripts/start-all.sh "$CONFIG_FILE"
