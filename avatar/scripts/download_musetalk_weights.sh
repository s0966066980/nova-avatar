#!/usr/bin/env bash
# Derived from Kedreamix/Linly-Talker-Stream; Apache-2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
# Use the project's pinned huggingface-hub; do not upgrade it with system pip.
# Set HF_ENDPOINT explicitly if a mirror is required. Revisions and SHA-256
# checksums live in scripts/musetalk_weights.py; any mismatch fails.
exec uv run --no-sync python scripts/musetalk_weights.py "$@"
