#!/usr/bin/env bash
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
#
# Nova Avatar kiosk launcher: opens the digital-human stage full screen on the
# venue host. The stage sees ?kiosk=1 and connects by itself and reconnects after
# a drop. Opening /stage.html in a normal browser keeps the click-to-enter flow.
#
# Usage: scripts/start-kiosk.sh [config]
#   NOVA_KIOSK_URL            full stage URL (default derived from the config)
#   NOVA_KIOSK_BROWSER        browser executable (default: first Chrome/Chromium found)
#   NOVA_KIOSK_PROFILE        browser profile directory (default: .local/kiosk-profile)
#   NOVA_KIOSK_WAIT_SECONDS   how long to wait for the web server (default 180)
#   NOVA_KIOSK_DRY_RUN=1      print the command instead of starting the browser
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="${1:-config/config.yaml}"
[[ "$CONFIG_FILE" = /* ]] || CONFIG_FILE="$PROJECT_ROOT/$CONFIG_FILE"

if [[ -n "${NOVA_KIOSK_URL:-}" ]]; then
    URL="$NOVA_KIOSK_URL"
else
    [[ -f "$CONFIG_FILE" ]] || { echo "找不到設定檔: $CONFIG_FILE" >&2; exit 1; }
    scheme=http
    if grep -Eq '^[[:space:]]*ssl:[[:space:]]*true([[:space:]]|$)' "$CONFIG_FILE"; then
        scheme=https
    fi
    URL="$scheme://localhost:3000/stage.html?kiosk=1"
fi

BROWSER="${NOVA_KIOSK_BROWSER:-}"
if [[ -z "$BROWSER" ]]; then
    for candidate in google-chrome-stable google-chrome chromium chromium-browser; do
        if command -v "$candidate" >/dev/null 2>&1; then
            BROWSER="$candidate"
            break
        fi
    done
fi
if [[ -z "$BROWSER" ]] && [[ "${NOVA_KIOSK_DRY_RUN:-0}" != "1" ]]; then
    echo "找不到 Chrome 或 Chromium，請安裝或設定 NOVA_KIOSK_BROWSER" >&2
    exit 1
fi

PROFILE_DIR="${NOVA_KIOSK_PROFILE:-$PROJECT_ROOT/.local/kiosk-profile}"

# --autoplay-policy and --use-fake-ui-for-media-stream replace the one click that
# a normal browser needs for sound and microphone permission.
# --allow-insecure-localhost accepts the self-signed certificate on localhost only.
FLAGS=(
    --kiosk
    --user-data-dir="$PROFILE_DIR"
    --no-first-run
    --no-default-browser-check
    --noerrdialogs
    --disable-infobars
    --disable-session-crashed-bubble
    --autoplay-policy=no-user-gesture-required
    --use-fake-ui-for-media-stream
    --allow-insecure-localhost
)

if [[ "${NOVA_KIOSK_DRY_RUN:-0}" == "1" ]]; then
    printf '%s' "${BROWSER:-<no-browser>}"
    printf ' %s' "${FLAGS[@]}" "$URL"
    printf '\n'
    exit 0
fi

mkdir -p "$PROFILE_DIR"

wait_seconds="${NOVA_KIOSK_WAIT_SECONDS:-180}"
echo "等待 Nova Avatar 前端就緒: $URL"
for ((elapsed = 0; elapsed < wait_seconds; elapsed += 2)); do
    if curl -sk --max-time 2 -o /dev/null "${URL%%\?*}"; then
        exec "$BROWSER" "${FLAGS[@]}" "$URL"
    fi
    sleep 2
done
echo "等待 ${wait_seconds} 秒後前端仍未就緒，仍嘗試開啟舞台，頁面會自動重連" >&2
exec "$BROWSER" "${FLAGS[@]}" "$URL"
