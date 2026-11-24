#!/usr/bin/env bash
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
#
# 建立 Matcha-TTS 微調專用環境：.local/matcha-train/venv（Python 3.10）與底模
# .local/matcha-base/pytorch_model_sherpa.bin。與主程式 .venv 完全分開，不會改動它。
# 可重複執行：已存在且通過檢查的部分不會重做；底模以固定 commit 下載並核對 SHA-256，
# 已存在但雜湊不符時會停下，不會自動覆蓋。
#
# 用法：bash scripts/setup-matcha-train.sh
# MATCHA_TRAIN_TORCH=cu124（預設，與主環境同為 torch 2.5.0+cu124，供訓練用）或 cpu
# （只裝 CPU 版 torch，供檢查與測試）。最後一步用 CPU 嚴格載入底模並跑數個假資料訓練步驟。
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

# torch 的 wheel 索引隨 GPU 版本而異，所以與其他依賴分開安裝。
uv pip install --python "$VENV/bin/python" \
    --index-url "https://download.pytorch.org/whl/$TORCH_VARIANT" \
    --extra-index-url https://pypi.org/simple --index-strategy unsafe-best-match \
    "torch==$TORCH_VERSION" "torchaudio==$TORCH_VERSION"
uv pip install --python "$VENV/bin/python" -r "$DEPS/requirements.txt"
# 上游 matcha-tts（MIT）不帶依賴安裝：它的 metadata 釘了 gradio 3.43.2、jupyter 等訓練用不到的套件。
uv pip install --python "$VENV/bin/python" --no-deps --require-hashes -r "$DEPS/matcha-tts.txt"

"$VENV/bin/python" -I "$PROJECT_ROOT/scripts/matcha_base_weights.py" --dir "$BASE_DIR"
CUDA_VISIBLE_DEVICES= "$VENV/bin/python" -I "$PROJECT_ROOT/scripts/matcha_train_env_check.py" \
    --checkpoint "$BASE_DIR/pytorch_model_sherpa.bin"
echo "✓ Matcha 訓練環境：$VENV"
echo "  底模：$BASE_DIR/pytorch_model_sherpa.bin"
