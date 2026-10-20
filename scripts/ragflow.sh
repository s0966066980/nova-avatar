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
    printf '用法：%s {install-docker|ensure-docker|prepare|up|down|status|is-running|pull-model|validate}\n' "$0"
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

require_compose() {
    local version
    if ! version="$(docker compose version --short 2>/dev/null)"; then
        printf '缺少 Docker Compose；請先執行 bash "%s" install-docker。\n' "$0" >&2
        return 1
    fi
    version="${version#v}"
    if [ "$(printf '%s\n' '2.40.0' "$version" | sort -V | head -n 1)" != '2.40.0' ]; then
        printf 'Docker Compose 需要 2.40.0 以上，目前為 %s。\n' "$version" >&2
        return 1
    fi
}

require_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        printf '尚未安裝 Docker；請先執行 bash "%s" install-docker。\n' "$0" >&2
        return 1
    fi
    if ! docker info >/dev/null 2>&1; then
        printf 'Docker 尚未就緒；請執行 bash "%s" ensure-docker 啟動並檢查連線。\n' "$0" >&2
        return 1
    fi
    require_compose
}

ensure_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        require_docker
        return 1
    fi
    require_compose
    if docker info >/dev/null 2>&1; then
        return 0
    fi

    # Only start the system daemon when the CLI targets its local socket.
    # A remote context or rootless socket must keep its own lifecycle.
    local endpoint
    if [ -n "${DOCKER_CONTEXT:-}" ]; then
        endpoint="$(docker context inspect "$DOCKER_CONTEXT" --format '{{.Endpoints.docker.Host}}')"
    elif [ -n "${DOCKER_HOST:-}" ]; then
        endpoint="$DOCKER_HOST"
    else
        endpoint="$(docker context inspect --format '{{.Endpoints.docker.Host}}')"
    fi
    case "$endpoint" in
        unix:///var/run/docker.sock|unix:///run/docker.sock) ;;
        *)
            printf '目前 Docker context 無法連線；請先啟動該 context 的服務或修正 DOCKER_HOST／DOCKER_CONTEXT。\n' >&2
            return 1
            ;;
    esac
    if ! command -v systemctl >/dev/null 2>&1 || \
        [ "$(systemctl show docker.service --property=LoadState --value 2>/dev/null)" != loaded ]; then
        printf '找不到本機 Docker systemd 服務；請先執行 bash "%s" install-docker。\n' "$0" >&2
        return 1
    fi
    if systemctl is-active --quiet docker; then
        printf 'Docker 服務已啟動，但目前帳號無法連線；請檢查 socket 權限、docker 群組與 Docker context。\n' >&2
        return 1
    fi

    printf '啟動本機 Docker 服務（必要時請在此終端輸入 sudo 密碼）...\n'
    if [ "$(id -u)" -eq 0 ]; then
        systemctl start docker
    elif ! sudo systemctl start docker; then
        printf '無法啟動 Docker；請在本機終端完成 sudo 驗證後重跑啟動指令。\n' >&2
        return 1
    fi
    local attempt
    for attempt in {1..30}; do
        if docker info >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    printf 'Docker 已嘗試啟動但仍無法連線；請檢查 systemctl status docker 與目前帳號的 docker 群組權限。\n' >&2
    return 1
}

wait_for_services() {
    local gateway deadline
    gateway="$(docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}')"
    deadline=$((SECONDS + STARTUP_TIMEOUT))
    printf '等待 RAGFlow 網頁、API 與嵌入服務就緒...\n'
    while [ "$SECONDS" -lt "$deadline" ]; do
        if curl --noproxy '*' -fsS --max-time 2 -o /dev/null http://127.0.0.1:8088/ 2>/dev/null && \
            curl --noproxy '*' -fsS --max-time 2 http://127.0.0.1:9380/api/v1/system/ping 2>/dev/null | grep -qx pong && \
            curl --noproxy '*' -fsS --max-time 2 -o /dev/null "http://$gateway:11435/api/tags" 2>/dev/null; then
            return 0
        fi
        sleep 1
    done
    printf '等待 RAGFlow 或嵌入服務就緒逾時；請執行 bash "%s" status，並檢查 journalctl --user -u nova-ragflow-embedding.service。\n' "$0" >&2
    return 1
}

case "${1:-}" in
    ensure-docker)
        ensure_docker
        ;;
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
        STARTUP_TIMEOUT="${NOVA_RAGFLOW_STARTUP_TIMEOUT:-180}"
        if [[ ! "$STARTUP_TIMEOUT" =~ ^[1-9][0-9]*$ ]]; then
            printf 'NOVA_RAGFLOW_STARTUP_TIMEOUT 必須為正整數秒數。\n' >&2
            exit 1
        fi
        ensure_docker
        prepare
        validate_compose
        compose up -d --wait --wait-timeout "$STARTUP_TIMEOUT"
        systemctl --user link "$EMBEDDING_UNIT" >/dev/null 2>&1 || true
        systemctl --user daemon-reload
        systemctl --user enable --now nova-ragflow-embedding.service
        wait_for_services
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
