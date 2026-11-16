#!/usr/bin/env bash
# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
#
# Generate a local Root CA and multi-SAN HTTPS server certificate for Nova Avatar.
# Uses mkcert when installed, and falls back to OpenSSL when mkcert is absent.

set -euo pipefail

CERT_PATH="${NOVA_SSL_CERT:-ssl_certs/localhost.crt}"
KEY_PATH="${NOVA_SSL_KEY:-ssl_certs/localhost.key}"
CA_DIR="${NOVA_SSL_CA_DIR:-}"
BACKEND="${NOVA_SSL_BACKEND:-auto}"
AUTO_DETECT="${NOVA_SSL_AUTO_DETECT:-1}"
FORCE_CA="${NOVA_SSL_FORCE_CA:-0}"
LEAF_DAYS="${NOVA_SSL_DAYS:-730}"
EXTRA_HOSTS=()

usage() {
    cat <<'EOF'
Usage: scripts/create_ssl_certs.sh [options] [HOST_OR_IP ...]

Options:
  --cert PATH         Output server certificate path (default: ssl_certs/localhost.crt)
  --key PATH          Output server private key path (default: ssl_certs/localhost.key)
  --ca-dir DIR        Directory for exported rootCA.pem / rootCA.crt (default: cert directory)
  --host HOST         Additional SAN hostname or IP (repeatable)
  --no-auto           Disable LAN / mDNS / Tailscale auto-detection
  --force-ca          Regenerate local Root CA even if rootCA.pem already exists (openssl)
  --backend MODE      Certificate backend: auto | mkcert | openssl (default: auto)
  --days N            Leaf certificate validity days for openssl (default: 730)
  -h, --help          Show this help message

Environment:
  NOVA_SSL_HOSTS      Comma- or space-separated extra SAN hosts/IPs
  NOVA_SSL_CERT       Same as --cert
  NOVA_SSL_KEY        Same as --key
  NOVA_SSL_CA_DIR     Same as --ca-dir
  NOVA_SSL_BACKEND    Same as --backend
  NOVA_SSL_AUTO_DETECT=0  Same as --no-auto
  NOVA_SSL_FORCE_CA=1     Same as --force-ca
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --cert)
            CERT_PATH="$2"
            shift 2
            ;;
        --key)
            KEY_PATH="$2"
            shift 2
            ;;
        --ca-dir)
            CA_DIR="$2"
            shift 2
            ;;
        --host)
            EXTRA_HOSTS+=("$2")
            shift 2
            ;;
        --no-auto)
            AUTO_DETECT=0
            shift
            ;;
        --force-ca)
            FORCE_CA=1
            shift
            ;;
        --backend)
            BACKEND="$2"
            shift 2
            ;;
        --days)
            LEAF_DAYS="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            while [[ $# -gt 0 ]]; do
                EXTRA_HOSTS+=("$1")
                shift
            done
            ;;
        -*)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
        *)
            EXTRA_HOSTS+=("$1")
            shift
            ;;
    esac
done

case "$BACKEND" in
    auto|mkcert|openssl) ;;
    *)
        echo "Unsupported --backend '$BACKEND' (expected auto, mkcert, or openssl)" >&2
        exit 2
        ;;
esac

mkdir -p "$(dirname "$CERT_PATH")" "$(dirname "$KEY_PATH")"
if [[ -z "$CA_DIR" ]]; then
    CA_DIR="$(dirname "$CERT_PATH")"
fi
mkdir -p "$CA_DIR"

SAN_HOSTS=()
add_host() {
    local candidate="${1:-}"
    candidate="${candidate#"${candidate%%[![:space:]]*}"}"
    candidate="${candidate%"${candidate##*[![:space:]]}"}"
    [[ -z "$candidate" ]] && return 0
    local existing
    for existing in "${SAN_HOSTS[@]}"; do
        if [[ "$existing" == "$candidate" ]]; then
            return 0
        fi
    done
    SAN_HOSTS+=("$candidate")
}

add_host "localhost"
add_host "127.0.0.1"
add_host "::1"

detect_hosts() {
    local short_host=""
    if command -v hostname >/dev/null 2>&1; then
        short_host="$(hostname -s 2>/dev/null || true)"
        if [[ -n "$short_host" && "$short_host" != "localhost" && "$short_host" != "localhost.localdomain" ]]; then
            add_host "${short_host}.local"
            add_host "$short_host"
        fi
    fi

    if command -v ip >/dev/null 2>&1; then
        local line iface addr
        while IFS= read -r line; do
            iface="$(awk '{print $2}' <<<"$line")"
            addr="$(sed -n 's/.*inet \([0-9.]*\)\/.*/\1/p' <<<"$line")"
            [[ -z "$addr" ]] && continue
            case "$iface" in
                lo|docker*|br-*|veth*|virbr*) continue ;;
            esac
            case "$addr" in
                127.*|169.254.*) continue ;;
            esac
            add_host "$addr"
        done < <(ip -4 -o addr show scope global 2>/dev/null || true)
    elif command -v hostname >/dev/null 2>&1; then
        local ip_addr
        for ip_addr in $(hostname -I 2>/dev/null || true); do
            case "$ip_addr" in
                127.*|169.254.*) continue ;;
                *) add_host "$ip_addr" ;;
            esac
        done
    fi

    if command -v tailscale >/dev/null 2>&1; then
        local ts_ip ts_dns=""
        while IFS= read -r ts_ip; do
            add_host "$ts_ip"
        done < <(tailscale ip -4 2>/dev/null || true)

        if command -v python3 >/dev/null 2>&1; then
            ts_dns="$(tailscale status --json 2>/dev/null | python3 -c 'import json,sys
try:
    data = json.load(sys.stdin)
    print(((data.get("Self") or {}).get("DNSName") or "").rstrip("."))
except Exception:
    pass' 2>/dev/null || true)"
        else
            ts_dns="$(tailscale status --json 2>/dev/null | awk '/"Self"[[:space:]]*:/,/\}/' | sed -n 's/.*"DNSName":[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1 | sed 's/\.$//' || true)"
        fi
        if [[ -n "$ts_dns" ]]; then
            add_host "$ts_dns"
        fi
    fi
}

if [[ "$AUTO_DETECT" == "1" ]]; then
    detect_hosts
fi

if [[ -n "${NOVA_SSL_HOSTS:-}" ]]; then
    IFS=', ' read -r -a _env_hosts <<<"${NOVA_SSL_HOSTS}"
    for h in "${_env_hosts[@]}"; do
        add_host "$h"
    done
fi

for h in "${EXTRA_HOSTS[@]}"; do
    add_host "$h"
done

selected_backend="$BACKEND"
if [[ "$selected_backend" == "auto" ]]; then
    if command -v mkcert >/dev/null 2>&1; then
        selected_backend="mkcert"
    else
        selected_backend="openssl"
    fi
fi

is_ip_addr() {
    local value="$1"
    if [[ "$value" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
        return 0
    fi
    if [[ "$value" == *:* ]]; then
        return 0
    fi
    return 1
}

run_mkcert() {
    if ! command -v mkcert >/dev/null 2>&1; then
        echo "mkcert is not installed. Install mkcert or re-run with --backend openssl." >&2
        exit 1
    fi
    if [[ "${NOVA_SSL_MKCERT_INSTALL:-1}" == "1" ]]; then
        mkcert -install >/dev/null 2>&1 || true
    fi
    mkcert -cert-file "$CERT_PATH" -key-file "$KEY_PATH" "${SAN_HOSTS[@]}"

    local caroot
    caroot="$(mkcert -CAROOT)"
    if [[ -f "$caroot/rootCA.pem" ]]; then
        cp -f "$caroot/rootCA.pem" "$CA_DIR/rootCA.pem"
        cp -f "$caroot/rootCA.pem" "$CA_DIR/rootCA.crt"
    fi
}

run_openssl() {
    if ! command -v openssl >/dev/null 2>&1; then
        echo "openssl is required when mkcert is not installed." >&2
        exit 1
    fi

    local ca_pem="$CA_DIR/rootCA.pem"
    local ca_crt="$CA_DIR/rootCA.crt"
    local ca_key="$CA_DIR/rootCA-key.pem"
    _NOVA_SSL_TMP_DIR="$(mktemp -d)"
    trap 'rm -rf "${_NOVA_SSL_TMP_DIR:-}"' EXIT
    local tmp_dir="$_NOVA_SSL_TMP_DIR"

    if [[ "$FORCE_CA" == "1" || ! -f "$ca_pem" || ! -f "$ca_key" ]]; then
        cat >"$tmp_dir/ca.cnf" <<'EOF'
[req]
distinguished_name = req_dn
x509_extensions = v3_ca
prompt = no

[req_dn]
O = Nova Avatar
CN = Nova Avatar Local CA

[v3_ca]
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints = critical, CA:TRUE
keyUsage = critical, digitalSignature, keyCertSign, cRLSign
EOF
        openssl genrsa -out "$ca_key" 2048 2>/dev/null
        chmod 600 "$ca_key"
        openssl req -x509 -new -nodes -key "$ca_key" -sha256 -days 3650 \
            -config "$tmp_dir/ca.cnf" -out "$ca_pem"
    fi
    cp -f "$ca_pem" "$ca_crt"

    local san_entries=()
    local host
    for host in "${SAN_HOSTS[@]}"; do
        if is_ip_addr "$host"; then
            san_entries+=("IP:${host}")
        else
            san_entries+=("DNS:${host}")
        fi
    done
    local san_csv
    san_csv="$(IFS=,; echo "${san_entries[*]}")"

    cat >"$tmp_dir/leaf.cnf" <<'EOF'
[req]
distinguished_name = req_dn
prompt = no

[req_dn]
O = Nova Avatar
CN = localhost
EOF

    cat >"$tmp_dir/leaf_ext.cnf" <<EOF
[v3_req]
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid,issuer
subjectAltName = ${san_csv}
EOF

    openssl genrsa -out "$KEY_PATH" 2048 2>/dev/null
    chmod 600 "$KEY_PATH"
    openssl req -new -key "$KEY_PATH" -config "$tmp_dir/leaf.cnf" -out "$tmp_dir/leaf.csr"
    openssl x509 -req -in "$tmp_dir/leaf.csr" \
        -CA "$ca_pem" -CAkey "$ca_key" \
        -CAserial "$tmp_dir/ca.srl" -CAcreateserial \
        -out "$CERT_PATH" -days "$LEAF_DAYS" -sha256 \
        -extfile "$tmp_dir/leaf_ext.cnf" -extensions v3_req 2>/dev/null
}

if [[ "$selected_backend" == "mkcert" ]]; then
    run_mkcert
else
    run_openssl
fi

echo "Nova Avatar SSL certificates generated (backend: $selected_backend)"
echo "  Server cert : $CERT_PATH"
echo "  Server key  : $KEY_PATH"
echo "  Root CA     : $CA_DIR/rootCA.pem (and $CA_DIR/rootCA.crt)"
echo "  SAN hosts   : ${SAN_HOSTS[*]}"
echo "  Device trust: import ONLY rootCA.pem / rootCA.crt (never rootCA-key.pem); see docs/https-device-trust.md"
