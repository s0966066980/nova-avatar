#!/usr/bin/env bash
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
#
# 建立 Fun-ASR-Nano-2512 服務專用的 venv（預設 ~/.venvs/fun-asr-nano），依
# integrations/fun-asr-nano/requirements.txt 的固定版本安裝。與 Nova 主環境分開：
# 解碼器 Qwen3 需要 transformers>=4.51，MuseTalk 釘 <4.47。torch 與主環境同為
# 2.5.0+cu124；沒有 GPU 的機器也能安裝（以 --device cpu 執行）。
#
# 用法：bash scripts/setup-fun-asr-nano.sh [venv 路徑]
# 其他路徑須設定 FUN_ASR_NANO_PYTHON=<venv>/bin/python 讓後端找到。
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${1:-$HOME/.venvs/fun-asr-nano}"
REQUIREMENTS="$PROJECT_ROOT/integrations/fun-asr-nano/requirements.txt"

if ! command -v uv >/dev/null 2>&1; then
    echo "❌ 需要 uv" >&2
    exit 1
fi
case "$VENV" in
    "$PROJECT_ROOT"|"$PROJECT_ROOT"/*)
        echo "❌ venv 須建立在專案目錄外：$VENV" >&2
        exit 1
        ;;
esac

if [ ! -x "$VENV/bin/python" ]; then
    uv venv --python 3.10 "$VENV"
fi
# requirements.txt 內含 PyPI 與 PyTorch cu124 兩個索引；torch 只在後者有 +cu124 版本。
uv pip sync --python "$VENV/bin/python" --index-strategy unsafe-best-match "$REQUIREMENTS"
"$VENV/bin/python" -c "import funasr, opencc, torch, transformers; print('funasr', funasr.__version__, 'transformers', transformers.__version__, 'torch', torch.__version__)"
echo "✓ Fun-ASR-Nano venv：$VENV"
if [ "$VENV" != "$HOME/.venvs/fun-asr-nano" ]; then
    echo "  後端啟動前設定 FUN_ASR_NANO_PYTHON=$VENV/bin/python"
fi
