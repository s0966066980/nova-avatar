#!/usr/bin/env bash
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$ROOT/.local/ragflow/upstream"
REF="v0.27.2"
COMPOSE_FILE="$DEPLOY_DIR/docker/docker-compose.yml"
OVERLAY_FILE="$ROOT/integrations/ragflow/compose.nova.yml"
EMBEDDING_UNIT="$ROOT/integrations/ragflow/nova-ragflow-embedding.service"

usage() {
    printf '用法：%s {install-docker|prepare|up|down|status|is-running|pull-model|validate}\n' "$0"
}

prepare() {
    if [ ! -d "$DEPLOY_DIR/.git" ]; then
        mkdir -p "$(dirname "$DEPLOY_DIR")"
        git clone --depth 1 --filter=blob:none --sparse --branch "$REF" \
            https://github.com/infiniflow/ragflow.git "$DEPLOY_DIR"
        git -C "$DEPLOY_DIR" sparse-checkout set docker
    fi
    local actual_ref
    actual_ref="$(git -C "$DEPLOY_DIR" describe --tags --exact-match HEAD)"
    if [ "$actual_ref" != "$REF" ]; then
        printf '預期 RAGFlow %s，但目前是 %s。\n' "$REF" "$actual_ref" >&2
        return 1
    fi
    python3 "$ROOT/scripts/ragflow_prepare.py"
}

compose() {
    docker compose --env-file "$DEPLOY_DIR/docker/.env" \
        -p nova-ragflow \
        -f "$COMPOSE_FILE" \
        -f "$OVERLAY_FILE" "$@"
}

validate_compose() {
    compose config --quiet
    compose config --format json | python3 "$ROOT/scripts/ragflow_validate.py"
}

require_docker() {
    if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
        printf 'Docker 尚未就緒。請先在本機執行 %s install-docker，必要時重新登入 docker 群組。\n' "$0" >&2
        return 1
    fi
    local version
    version="$(docker compose version --short)"
    if [ "$(printf '%s\n' '2.40.0' "$version" | sort -V | head -n 1)" != '2.40.0' ]; then
        printf 'Docker Compose 需要 2.40.0 以上，目前為 %s。\n' "$version" >&2
        return 1
    fi
}

case "${1:-}" in
    install-docker)
        if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
            if ! docker info >/dev/null 2>&1; then
                if [ "$(id -u)" -eq 0 ]; then
                    systemctl enable --now docker
                else
                    sudo systemctl enable --now docker
                fi
            fi
            printf '沿用已安裝的 Docker 與 Compose。\n'
            exit 0
        fi
        packages=(docker.io docker-compose-v2)
        if dpkg-query -W -f='${Status}' containerd.io 2>/dev/null | grep -q '^install ok installed$'; then
            packages=(docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin)
        fi
        if [ "$(id -u)" -eq 0 ]; then
            apt-get update
            apt-get install -y "${packages[@]}"
            systemctl enable --now docker
        else
            sudo apt-get update
            sudo apt-get install -y "${packages[@]}"
            sudo systemctl enable --now docker
        fi
        printf 'Docker 已安裝。若 docker info 顯示權限錯誤，請重新登入後重試。\n'
        ;;
    prepare)
        prepare
        ;;
    validate)
        prepare
        require_docker
        validate_compose
        ;;
    up)
        prepare
        require_docker
        validate_compose
        compose up -d
        systemctl --user link "$EMBEDDING_UNIT" >/dev/null 2>&1 || true
        systemctl --user daemon-reload
        systemctl --user enable --now nova-ragflow-embedding.service
        printf 'RAGFlow 網頁：http://127.0.0.1:8088；API：http://127.0.0.1:9380\n'
        ;;
    down)
        require_docker
        systemctl --user disable --now nova-ragflow-embedding.service 2>/dev/null || true
        compose down
        ;;
    status)
        require_docker
        compose ps
        printf 'RAGFlow 嵌入服務：%s\n' "$(systemctl --user is-active nova-ragflow-embedding.service 2>/dev/null || true)"
        ;;
    is-running)
        require_docker
        if [ -n "$(docker ps --filter label=com.docker.compose.project=nova-ragflow --format '{{.ID}}')" ] || \
            systemctl --user is-active --quiet nova-ragflow-embedding.service; then
            exit 0
        fi
        exit 1
        ;;
    pull-model)
        if ollama show bge-m3 >/dev/null 2>&1; then
            printf '已存在 BGE-M3 模型，沿用主機現有檔案。\n'
        else
            ollama pull bge-m3
        fi
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
