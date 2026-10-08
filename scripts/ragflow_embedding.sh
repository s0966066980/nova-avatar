#!/usr/bin/env bash
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

# A separate GPU-backed Ollama process for RAGFlow. It reuses the locally
# installed binary and read-only model files, not Nova's language-model server.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OLLAMA_BIN="$(command -v ollama || true)"
OLLAMA_BIN="${NOVA_RAGFLOW_OLLAMA_BIN:-${OLLAMA_BIN:-$ROOT/.local/ragflow/ollama/bin/ollama}}"

GATEWAY="$(docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}')"
if [[ ! "$GATEWAY" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    printf '找不到 RAGFlow 獨立網路閘道。\n' >&2
    exit 1
fi

export OLLAMA_HOST="$GATEWAY:11435"
if [[ -d /usr/share/ollama/.ollama/models ]]; then
    DEFAULT_MODELS=/usr/share/ollama/.ollama/models
else
    DEFAULT_MODELS="$ROOT/.local/ragflow/ollama-models"
fi
export OLLAMA_MODELS="${NOVA_RAGFLOW_OLLAMA_MODELS:-$DEFAULT_MODELS}"
export OLLAMA_NO_CLOUD=1
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_LOADED_MODELS=1
# Keep the small dedicated embedding model resident to avoid cold loads during
# Nova's bounded retrieval request. Override in the service environment if needed.
export OLLAMA_KEEP_ALIVE="${NOVA_RAGFLOW_KEEP_ALIVE:--1}"
export CUDA_VISIBLE_DEVICES="${NOVA_RAGFLOW_CUDA_VISIBLE_DEVICES:-0}"

exec "$OLLAMA_BIN" serve
