#!/usr/bin/env bash
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

# JetPack 7 (L4T R39), AGX Orin SM 8.7, Python 3.11.
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
export PATH="$HOME/.local/bin:$PATH"
test "$(uname -m)" = aarch64 || { echo 'Expected ARM64 Jetson.'; exit 1; }
rg -q '^# R39 ' /etc/nv_tegra_release || { echo 'This setup requires JetPack 7 / L4T R39.'; exit 1; }
for command in uv node npm ffmpeg cmake ninja gcc g++ pkg-config; do
    command -v "$command" >/dev/null || { echo "Missing $command; see docs/jetson-orin.md"; exit 1; }
done
export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
export PATH="$CUDA_HOME/bin:$PATH"
test -x "$CUDA_HOME/bin/nvcc"
if [ -d .venv ]; then
    if ! .venv/bin/python -c 'import platform,sys; assert platform.machine() == "aarch64"; assert sys.version_info[:2] == (3,11)' 2>/dev/null; then
        mv .venv ".venv-x86-backup-$(date +%Y%m%d-%H%M%S)"
    fi
fi
if [ ! -d .venv ]; then
    uv venv --python 3.11
fi
bash scripts/build-jetson-ctranslate2.sh
uv sync --extra vad --extra musetalk --extra funasr
.venv/bin/python scripts/fix-jetson-wheel-tags.py
.venv/bin/python -c 'import torch; assert torch.cuda.is_available(); x=torch.randn(64,64,device="cuda"); assert (x@x).is_cuda; torch.cuda.synchronize(); print(torch.cuda.get_device_name(0))'
npm ci --prefix web
npm run build --prefix web
uv run python scripts/check-cuda.py
