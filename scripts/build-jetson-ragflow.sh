#!/usr/bin/env bash
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/.local/ragflow/arm64-source"
UPSTREAM="$ROOT/.local/ragflow/upstream"
ASSETS="$ROOT/.local/ragflow/arm64-assets"
COMMIT=a024bea0cd93f39e6652a42bf84dd20c55bc560b
IMAGE=nova-avatar/ragflow:v0.27.2-arm64
[[ "$(uname -m)" == aarch64 ]] || { echo 'This build requires a native ARM64 host.' >&2; exit 1; }
bash "$ROOT/scripts/ragflow.sh" prepare
if [[ ! -e "$SOURCE/.git" ]]; then
    git -C "$UPSTREAM" worktree add --detach "$SOURCE" "$COMMIT"
    git -C "$SOURCE" sparse-checkout disable
fi
[[ "$(git -C "$SOURCE" rev-parse HEAD)" == "$COMMIT" ]] || { echo 'Unexpected RAGFlow source commit.' >&2; exit 1; }
cd "$ROOT"
uv run --with nltk==3.10.3 --with huggingface-hub==1.3.1 python scripts/ragflow_arm64_assets.py "$ASSETS"
docker buildx build --platform linux/arm64 --load \
    --build-context "ragflow-assets=$ASSETS" \
    --file "$ROOT/integrations/ragflow/Dockerfile.arm64" \
    --tag "$IMAGE" "$SOURCE"
[[ "$(docker image inspect "$IMAGE" --format '{{.Architecture}}')" == arm64 ]]
docker run --rm --entrypoint python "$IMAGE" -c \
    'import platform, onnxruntime, xgboost; assert platform.machine() == "aarch64"; print("ARM64 Python / ONNX Runtime / XGBoost verified")'
if ! command -v ollama >/dev/null 2>&1 && [[ ! -x "$ROOT/.local/ragflow/ollama/bin/ollama" ]]; then
    bash "$ROOT/scripts/setup-ragflow-embedding.sh"
fi
echo "Built $IMAGE; start with: bash scripts/ragflow.sh up"
