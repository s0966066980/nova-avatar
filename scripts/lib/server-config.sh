#!/usr/bin/env bash
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

# Shared config inspection helpers for Nova Avatar startup and service scripts.

read_protocol() {
    local cfg="$1"
    if [ -f "$cfg" ] && grep -Eq '^[[:space:]]*ssl:[[:space:]]*true([[:space:]]|$)' "$cfg"; then
        printf 'https\n'
    else
        printf 'http\n'
    fi
}

read_backend_port() {
    local cfg="$1"
    local port=""
    if [ -f "$cfg" ]; then
        port="$(awk '/^[[:space:]]*listenport:[[:space:]]*[0-9]+/ {print $2; exit}' "$cfg" 2>/dev/null || true)"
    fi
    printf '%s\n' "${port:-8010}"
}
