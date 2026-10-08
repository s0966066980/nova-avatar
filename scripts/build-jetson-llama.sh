#!/usr/bin/env bash
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
export PATH="$HOME/.local/bin:$PATH"
export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
export CUDA_HOME="$(readlink -f "$CUDA_HOME")"
LLAMA_SOURCE="$PROJECT_ROOT/.local/jetson/llama.cpp"
if [ ! -d "$LLAMA_SOURCE/.git" ]; then
    mkdir -p "$PROJECT_ROOT/.local/jetson"
    git clone --depth 1 --branch v0.5.0 https://github.com/ggml-org/llama.cpp.git "$LLAMA_SOURCE"
fi
test "$(git -C "$LLAMA_SOURCE" rev-parse HEAD)" = 7fe450e19305b828c199d602c23a8337aaa1f03b
cmake -S "$LLAMA_SOURCE" -B "$LLAMA_SOURCE/build" -G Ninja \
    -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=87 \
    -DCMAKE_CUDA_COMPILER="$CUDA_HOME/bin/nvcc" \
    -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_CURL=OFF \
    -DCMAKE_BUILD_TYPE=Release
cmake --build "$LLAMA_SOURCE/build" --target llama-server -j "${NOVA_BUILD_JOBS:-8}"
mkdir -p "$HOME/.local/bin"
ln -sfn "$LLAMA_SOURCE/build/bin/llama-server" "$HOME/.local/bin/llama-server"
"$LLAMA_SOURCE/build/bin/llama-server" --list-devices

if [ "${1:-}" = --download-model ]; then
    mkdir -p llama
    curl -L --fail --retry 3 --continue-at - \
        'https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/e87f176479d0855a907a41277aca2f8ee7a09523/Qwen3.5-4B-UD-Q4_K_XL.gguf' \
        -o llama/Qwen3.5-4B-UD-Q4_K_XL.gguf
    echo 'b252c5610a42ca82d20fe2a12813e9d069eed89292907e26c783eeb0bc961bc7  llama/Qwen3.5-4B-UD-Q4_K_XL.gguf' | sha256sum -c -
fi
