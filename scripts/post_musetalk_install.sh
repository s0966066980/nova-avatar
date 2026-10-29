#!/bin/bash

# Derived from Kedreamix/Linly-Talker-Stream; Apache-2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

# Post-installation script for MuseTalk avatar
# This script configures mmdet in the project .venv after installation

set -euo pipefail  # Exit on error

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Always patch the project's own environment, never an unrelated active
# VIRTUAL_ENV or the system Python.
VENV_PATH="$PROJECT_ROOT/.venv"

echo "MuseTalk Post-Installation Script"
echo "=================================="

if [[ ! -d "$VENV_PATH" ]]; then
    echo "❌ 找不到專案虛擬環境: $VENV_PATH" >&2
    exit 1
fi

echo "Using virtual environment: $VENV_PATH"

# 1. Modify mmcv_maximum_version in mmdet's __init__.py file
shopt -s nullglob
MMDET_INIT_FILES=("$VENV_PATH"/lib/python3.*/site-packages/mmdet/__init__.py)
shopt -u nullglob

if [[ ${#MMDET_INIT_FILES[@]} -eq 0 ]]; then
    echo "❌ 專案虛擬環境中找不到 mmdet/__init__.py；請先完成 mmdet 安裝" >&2
    exit 1
fi

for MMDET_INIT_FILE in "${MMDET_INIT_FILES[@]}"; do
    echo "Found mmdet at: $MMDET_INIT_FILE"
    echo "Modifying mmcv_maximum_version in mmdet/__init__.py..."
    sed -i "s/mmcv_maximum_version = '[^']*'/mmcv_maximum_version = '2.2.1'/g" "$MMDET_INIT_FILE"
    if ! grep -q "mmcv_maximum_version = '2.2.1'" "$MMDET_INIT_FILE"; then
        echo "❌ 無法修補 $MMDET_INIT_FILE 的 mmcv_maximum_version" >&2
        exit 1
    fi
    echo "✓ mmcv_maximum_version has been updated to 2.2.1"
done

echo ""
echo "=================================="
echo "✓ Post-installation completed!"
echo "=================================="
