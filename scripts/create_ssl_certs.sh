#!/usr/bin/env bash
# Derived from Kedreamix/Linly-Talker-Stream; Apache-2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.
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
temporary="$(mktemp -d ssl_certs/.new-XXXXXX)"
trap 'rm -rf "$temporary"' EXIT
openssl req -newkey rsa:2048 -nodes -x509 -days 365 \
    -subj '/CN=localhost' \
    -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1,IP:::1' \
    -keyout "$temporary/localhost.key" -out "$temporary/localhost.crt"
chmod 600 "$temporary/localhost.key"
mv "$temporary/localhost.key" "$temporary/localhost.crt" ssl_certs/
echo 'Created local self-signed SSL certificate in ssl_certs/.'
