#!/usr/bin/env bash
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

# A separate CPU-only Ollama process for RAGFlow. It reuses the locally
# installed binary and read-only model files, not Nova's language-model server.
set -euo pipefail

GATEWAY="$(docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}')"
if [[ ! "$GATEWAY" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    printf '找不到 RAGFlow 獨立網路閘道。\n' >&2
    exit 1
fi

export OLLAMA_HOST="$GATEWAY:11435"
export OLLAMA_MODELS=/usr/share/ollama/.ollama/models
export OLLAMA_NO_CLOUD=1
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_KEEP_ALIVE=5m
export CUDA_VISIBLE_DEVICES=-1

exec /usr/local/bin/ollama serve
