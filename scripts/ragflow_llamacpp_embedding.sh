#!/usr/bin/env bash
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

# RAGFlow's BGE-M3 query and document embeddings on the CPU (issue 15). The
# GPU-backed Ollama it replaces spent ~0.5 s per query on fixed overhead;
# llama.cpp embeds a query in ~0.05 s with the same weights and vectors.
# Listens only on the Docker bridge gateway, where RAGFlow's containers reach
# it as host.docker.internal. CUDA sees no device, so nothing loads on the GPU.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL="$ROOT/models/ragflow/bge-m3-f16.gguf"
PORT=11437
# BGE-M3 is not causal: llama.cpp embeds an input in a single micro-batch, so
# the context, batch and micro-batch sizes are one limit. Longer RAGFlow chunks
# are rejected (the default chunk is 512 tokens). Peak RSS ~3.5 GB at 2048.
CONTEXT=2048
THREADS="${NOVA_RAGFLOW_EMBEDDING_THREADS:-4}"

SERVER="${NOVA_RAGFLOW_LLAMA_SERVER:-}"
if [ -z "$SERVER" ]; then
    SERVER="$(command -v llama-server || printf '%s' "$HOME/llama/llama.cpp/build/bin/llama-server")"
fi
if [ ! -x "$SERVER" ]; then
    printf '找不到 llama-server（%s）；可用 NOVA_RAGFLOW_LLAMA_SERVER 指定。\n' "$SERVER" >&2
    exit 1
fi
if [ ! -f "$MODEL" ]; then
    printf '找不到 %s；請先執行 bash scripts/ragflow.sh pull-model。\n' "$MODEL" >&2
    exit 1
fi

GATEWAY="$(docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}')"
if [[ ! "$GATEWAY" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    printf '找不到 RAGFlow 獨立網路閘道。\n' >&2
    exit 1
fi

export CUDA_VISIBLE_DEVICES=""
exec "$SERVER" -m "$MODEL" --alias bge-m3 --embedding --pooling cls \
    --host "$GATEWAY" --port "$PORT" -ngl 0 -t "$THREADS" -np 1 \
    -c "$CONTEXT" -b "$CONTEXT" -ub "$CONTEXT" --no-webui
