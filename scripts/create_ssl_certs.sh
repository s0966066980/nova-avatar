#!/usr/bin/env bash
# Derived from Kedreamix/Linly-Talker-Stream; Apache-2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.
#
# Usage: bash scripts/create_ssl_certs.sh [extra-hostname-or-ip ...]
# Prefers mkcert (local CA that admin devices trust once); falls back to a
# self-signed certificate. NOVA_SSL_SELF_SIGNED=1 forces the fallback.
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
mkdir -p ssl_certs
if [[ -s ssl_certs/localhost.key && -s ssl_certs/localhost.crt ]]; then
    echo 'Existing SSL certificate retained in ssl_certs/.'
    exit 0
fi
if [[ -e ssl_certs/localhost.key || -e ssl_certs/localhost.crt ]]; then
    echo 'Incomplete certificate pair in ssl_certs/; restore or move it before regenerating.' >&2
    exit 1
fi

# Admins reach the console over the LAN/VPN, so cover this host's names too.
names=(localhost 127.0.0.1 ::1)
host_name="$(hostname 2>/dev/null || true)"
[[ -n "$host_name" && "$host_name" != localhost ]] && names+=("$host_name")
read -r -a host_addresses <<< "$(hostname -I 2>/dev/null || true)"
names+=("${host_addresses[@]}" "$@")

temporary="$(mktemp -d ssl_certs/.new-XXXXXX)"
trap 'rm -rf "$temporary"' EXIT
if [[ "${NOVA_SSL_SELF_SIGNED:-0}" != 1 ]] && command -v mkcert >/dev/null 2>&1; then
    mkcert -key-file "$temporary/localhost.key" -cert-file "$temporary/localhost.crt" "${names[@]}"
    kind='mkcert local-CA'
else
    san=''
    for name in "${names[@]}"; do
        if [[ "$name" == *:* || "$name" =~ ^[0-9]+(\.[0-9]+){3}$ ]]; then
            san+="${san:+,}IP:$name"
        else
            san+="${san:+,}DNS:$name"
        fi
    done
    openssl req -newkey rsa:2048 -nodes -x509 -days 365 \
        -subj '/CN=localhost' \
        -addext "subjectAltName=$san" \
        -keyout "$temporary/localhost.key" -out "$temporary/localhost.crt"
    kind='self-signed'
fi
chmod 600 "$temporary/localhost.key"
mv "$temporary/localhost.key" "$temporary/localhost.crt" ssl_certs/
echo "Created local $kind SSL certificate in ssl_certs/ for: ${names[*]}"
if [[ "$kind" == mkcert* ]]; then
    ca_root="$(mkcert -CAROOT)"
    echo "Trust once: run 'mkcert -install' on this host, and import"
    echo "  $ca_root/rootCA.pem"
    echo "into each admin device. Never copy rootCA-key.pem off this host."
fi
