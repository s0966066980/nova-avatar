#!/usr/bin/env bash
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

# Install the official native Ollama release locally, without changing the
# host's language-model service. Release asset hashes come from GitHub.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION=v0.35.1
DEST="$ROOT/.local/ragflow/ollama"
CACHE="$ROOT/.local/ragflow/downloads"
[[ "$(uname -m)" == aarch64 ]] || { echo 'This installer requires ARM64.' >&2; exit 1; }
mkdir -p "$DEST" "$CACHE"
fetch() {
    local name="$1" digest="$2" target="$CACHE/$1"
    if ! printf '%s  %s\n' "$digest" "$target" | sha256sum --check --status 2>/dev/null; then
        curl --fail --location --retry 3 --continue-at - \
            "https://github.com/ollama/ollama/releases/download/$VERSION/$name" \
            --output "$target"
    fi
    printf '%s  %s\n' "$digest" "$target" | sha256sum --check --status
    tar --zstd -xf "$target" -C "$DEST"
}
fetch ollama-linux-arm64.tar.zst b1b1c85d25136b256d3740f6ecd2f7c0105e8ca71642fd6ff2fc199f3cefd69d
# Jetson needs the JetPack CUDA runner in addition to the generic ARM64 bundle.
if [[ -f /etc/nv_tegra_release ]]; then
    fetch ollama-linux-arm64-jetpack6.tar.zst e9a6b9a9e71c4eeefd8b7955354e08a088e0a7afcc5186992f906fa080bc0af8
fi
"$DEST/bin/ollama" --version
echo "Native embedding runtime installed: $VERSION"
