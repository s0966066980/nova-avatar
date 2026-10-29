#!/usr/bin/env bash
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
#
# Nova Avatar kiosk launcher: opens the digital-human stage full screen on the
# venue host. The backend serves the stage (port 8010, same origin as its API)
# and answers loopback clients only. The stage sees ?kiosk=1, connects by itself
# and reconnects after a drop. Opening /stage.html in a normal browser keeps the
# click-to-enter flow.
#
# Usage: scripts/start-kiosk.sh [config]
#   NOVA_KIOSK_URL            full stage URL (default derived from the config);
#                             only this URL's origin may use the microphone
#   NOVA_KIOSK_BROWSER        browser executable (default: first Chrome/Chromium found)
#   NOVA_KIOSK_PROFILE        browser profile directory (default: .local/kiosk-profile)
#   NOVA_KIOSK_WAIT_SECONDS   how long to wait for the backend (default 180)
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
    URL="$scheme://localhost:8010/stage.html?kiosk=1"
fi
# scheme://host[:port], the only origin allowed to use the microphone.
ORIGIN="$(printf '%s' "$URL" | sed -E 's#^([A-Za-z][A-Za-z0-9+.-]*://[^/?#]+).*#\1#')"

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

# --autoplay-policy replaces the click a normal browser needs before playing
# sound. The microphone is granted by the kiosk profile to the stage origin
# only (allow_stage_microphone below), not to every page.
FLAGS=(
    --kiosk
    --user-data-dir="$PROFILE_DIR"
    --no-first-run
    --no-default-browser-check
    --noerrdialogs
    --disable-infobars
    --disable-session-crashed-bubble
    --autoplay-policy=no-user-gesture-required
)
# HTTPS uses the self-signed localhost certificate from
# scripts/create_ssl_certs.sh; this accepts it for localhost only.
if [[ "$URL" == https://* ]]; then
    FLAGS+=(--allow-insecure-localhost)
fi

# Chrome keeps site permissions per profile in Default/Preferences. Allow the
# microphone for the stage origin, block it for every other origin, and keep the
# rest of the profile. Chrome's AudioCaptureAllowedUrls policy would do the same,
# but on Linux policies are machine-wide files under /etc and need root.
allow_stage_microphone() {
    mkdir -p "$PROFILE_DIR/Default"
    python3 - "$PROFILE_DIR/Default/Preferences" "$ORIGIN" <<'PY'
import json
import os
import sys

path, origin = sys.argv[1], sys.argv[2]
try:
    with open(path, encoding="utf-8") as handle:
        preferences = json.load(handle)
except (OSError, ValueError):
    preferences = {}
if not isinstance(preferences, dict):
    preferences = {}
profile = preferences.setdefault("profile", {})
profile.setdefault("default_content_setting_values", {})["media_stream_mic"] = 2
exceptions = profile.setdefault("content_settings", {}).setdefault("exceptions", {})
exceptions["media_stream_mic"] = {f"{origin},*": {"setting": 1}}
partial = path + ".nova-partial"
with open(partial, "w", encoding="utf-8") as handle:
    json.dump(preferences, handle)
os.replace(partial, path)
PY
}

if [[ "${NOVA_KIOSK_DRY_RUN:-0}" == "1" ]]; then
    printf '%s' "${BROWSER:-<no-browser>}"
    printf ' %s' "${FLAGS[@]}" "$URL"
    printf '\n'
    exit 0
fi

allow_stage_microphone

wait_seconds="${NOVA_KIOSK_WAIT_SECONDS:-180}"
echo "等待 Nova Avatar 後端就緒: $URL"
for ((elapsed = 0; elapsed < wait_seconds; elapsed += 2)); do
    if curl -sk --max-time 2 -o /dev/null "${URL%%\?*}"; then
        exec "$BROWSER" "${FLAGS[@]}" "$URL"
    fi
    sleep 2
done
echo "等待 ${wait_seconds} 秒後後端仍未就緒，仍嘗試開啟舞台，頁面會自動重連" >&2
exec "$BROWSER" "${FLAGS[@]}" "$URL"
