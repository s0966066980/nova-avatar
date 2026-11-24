#!/usr/bin/env bash
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
#
# Build the Matcha-TTS fine-tuning environment: .local/matcha-train/venv (Python 3.10) and
# the base weights .local/matcha-base/pytorch_model_sherpa.bin. It is completely separate
# from the application's .venv and never touches it.
# Safe to re-run: parts that already exist and pass their checks are not redone. The base
# weights are downloaded at a pinned commit and verified against a SHA-256; if a file is
# already there with a different hash the script stops instead of overwriting it.
#
# Usage: bash scripts/setup-matcha-train.sh
# MATCHA_TRAIN_TORCH=cu124 (default; the same torch 2.5.0+cu124 as the main environment,
# for training) or cpu (CPU-only torch, for checks and tests). The last step loads the base
# weights strictly on the CPU and runs a few training steps on fake data.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRAIN_DIR="$PROJECT_ROOT/.local/matcha-train"
BASE_DIR="$PROJECT_ROOT/.local/matcha-base"
VENV="$TRAIN_DIR/venv"
DEPS="$PROJECT_ROOT/integrations/matcha-train"
TORCH_VARIANT="${MATCHA_TRAIN_TORCH:-cu124}"
TORCH_VERSION="2.5.0"

if ! command -v uv >/dev/null 2>&1; then
    echo "❌ 需要 uv" >&2
    exit 1
fi
case "$TORCH_VARIANT" in
    cu124|cpu) ;;
    *)
        echo "❌ MATCHA_TRAIN_TORCH 只能是 cu124 或 cpu：$TORCH_VARIANT" >&2
        exit 1
        ;;
esac

if [ ! -x "$VENV/bin/python" ]; then
    uv venv --python 3.10 "$VENV"
fi

# The torch wheel index depends on the GPU build, so torch is installed apart from the other dependencies.
uv pip install --python "$VENV/bin/python" \
    --index-url "https://download.pytorch.org/whl/$TORCH_VARIANT" \
    --extra-index-url https://pypi.org/simple --index-strategy unsafe-best-match \
    "torch==$TORCH_VERSION" "torchaudio==$TORCH_VERSION"
uv pip install --python "$VENV/bin/python" -r "$DEPS/requirements.txt"
# Upstream matcha-tts (MIT) is installed without its dependencies: its metadata pins gradio 3.43.2,
# jupyter and other packages that training does not need.
uv pip install --python "$VENV/bin/python" --no-deps --require-hashes -r "$DEPS/matcha-tts.txt"

"$VENV/bin/python" -I "$PROJECT_ROOT/scripts/matcha_base_weights.py" --dir "$BASE_DIR"
CUDA_VISIBLE_DEVICES= "$VENV/bin/python" -I "$PROJECT_ROOT/scripts/matcha_train_env_check.py" \
    --checkpoint "$BASE_DIR/pytorch_model_sherpa.bin"
echo "✓ Matcha 訓練環境：$VENV"
echo "  底模：$BASE_DIR/pytorch_model_sherpa.bin"
