#!/usr/bin/env bash
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

# Run after setup-env.sh and downloading the MuseTalk weights.
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
    echo 'Usage: bash scripts/setup-tensorrt.sh [builder options]'
    echo 'Installs CUDA 12 TensorRT, builds/checks engines, then enables verified speedups.'
    echo 'Options: --verify-only, --batch-size N, --components unet vae, --config PATH'
    exit 0
fi
command -v uv >/dev/null || { echo 'Install uv first.' >&2; exit 1; }
command -v nvidia-smi >/dev/null || { echo 'NVIDIA driver is required.' >&2; exit 1; }
[[ "$(uname -sm)" == 'Linux x86_64' ]] || { echo 'This installer supports Linux x86_64.' >&2; exit 1; }
[[ -x .venv/bin/python ]] || { echo 'Run bash scripts/setup-env.sh musetalk first.' >&2; exit 1; }
# Preserve manually built mmcv and other installed providers (e.g. FunASR).
uv sync --inexact --extra vad --extra musetalk --extra tensorrt
uv run --no-sync python -c 'import torch, tensorrt as trt; assert torch.cuda.is_available(); assert trt.Builder(trt.Logger()); print("GPU:", torch.cuda.get_device_name(), "TensorRT:", trt.__version__)'
uv run --no-sync python scripts/build-musetalk-tensorrt.py --enable "$@"
