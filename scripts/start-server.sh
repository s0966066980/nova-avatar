#!/usr/bin/env bash
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

# ========================================
# Nova Avatar - 單一入口生產啟動指令碼 (:8010)
# 由後端直接託管 web/dist，不啟動 Vite :3000
# ========================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$PROJECT_ROOT/web"
CONFIG_FILE="config/config.yaml"
AUTO_BUILD="${NOVA_AUTO_BUILD_WEB:-0}"
SYSTEMD_MODE=0
BACKEND_PID=""
RAGFLOW_OWNED=0

# shellcheck source=lib/server-config.sh
. "$PROJECT_ROOT/scripts/lib/server-config.sh"

show_usage() {
    echo -e "${YELLOW}使用方法:${NC}"
    echo -e "${YELLOW}  $0 [--build] [--systemd] [config/file.yaml]${NC}"
    echo ""
    echo -e "${YELLOW}說明:${NC}"
    echo -e "${YELLOW}  僅啟動 :8010 後端並直接提供 web/dist 靜態頁面（控制台 / 與舞台 /stage.html）。${NC}"
    echo -e "${YELLOW}  --build    若 web/dist 缺失或落後前端原始碼，自動執行 npm run build。${NC}"
    echo -e "${YELLOW}  --systemd  以前景模式直接執行（供 systemd Type=simple 使用）。${NC}"
    echo ""
}

while [ $# -gt 0 ]; do
    case "$1" in
        --help|-h)
            show_usage
            exit 0
            ;;
        --build)
            AUTO_BUILD=1
            shift
            ;;
        --systemd)
            SYSTEMD_MODE=1
            shift
            ;;
        *)
            CONFIG_FILE="$1"
            shift
            ;;
    esac
done

web_dist_is_stale() {
    local ref="$FRONTEND_DIR/dist/index.html"
    [ -f "$ref" ] || return 0
    local targets=()
    for candidate in "$FRONTEND_DIR/src" "$FRONTEND_DIR/index.html" "$FRONTEND_DIR/stage.html" "$FRONTEND_DIR/vite.config.js" "$FRONTEND_DIR/package.json"; do
        [ -e "$candidate" ] && targets+=("$candidate")
    done
    [ "${#targets[@]}" -gt 0 ] || return 1
    [ -n "$(find "${targets[@]}" -newer "$ref" -print -quit 2>/dev/null)" ]
}

build_web_dist() {
    if ! command -v npm >/dev/null 2>&1 || [ ! -d "$FRONTEND_DIR/node_modules" ]; then
        return 1
    fi
    echo -e "${YELLOW}📦 正在建置前端資源 web/dist...${NC}"
    (cd "$FRONTEND_DIR" && npm run build)
}

ensure_web_dist() {
    local dist_index="$FRONTEND_DIR/dist/index.html"
    local dist_stage="$FRONTEND_DIR/dist/stage.html"

    if [ ! -f "$dist_index" ] || [ ! -f "$dist_stage" ]; then
        if [ "$AUTO_BUILD" = 1 ]; then
            echo -e "${YELLOW}⚠ 找不到完整的前端建置產物 web/dist，正在自動建置...${NC}"
            if build_web_dist; then
                echo -e "${GREEN}✓${NC} web/dist 建置完成"
                return 0
            fi
            echo -e "${RED}❌ 錯誤: 找不到 web/dist（index.html / stage.html），且缺少 npm 或 web/node_modules 無法自動建置${NC}" >&2
            echo -e "${YELLOW}請先執行: cd web && npm install && npm run build${NC}" >&2
            exit 1
        fi
        echo -e "${RED}❌ 錯誤: 找不到完整的前端建置產物 web/dist（index.html / stage.html）${NC}" >&2
        echo -e "${YELLOW}請先執行: cd web && npm run build（或加上 --build / NOVA_AUTO_BUILD_WEB=1）${NC}" >&2
        exit 1
    fi

    if web_dist_is_stale; then
        if [ "$AUTO_BUILD" = 1 ]; then
            if ! build_web_dist; then
                echo -e "${RED}❌ 錯誤: web/dist 落後前端原始碼，且找不到 npm 或 web/node_modules 無法自動重建${NC}"
                exit 1
            fi
            echo -e "${GREEN}✓${NC} web/dist 已更新"
        else
            echo -e "${YELLOW}⚠ 警告: web/dist 落後前端原始碼；請執行 cd web && npm run build（或加上 --build）${NC}"
        fi
    else
        echo -e "${GREEN}✓${NC} 前端建置產物 web/dist 已就緒"
    fi
}

cleanup() {
    local status=$?
    trap - EXIT
    echo ""
    echo -e "${YELLOW}🛑 正在停止單一入口服務...${NC}"
    if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        kill "$BACKEND_PID" 2>/dev/null || true
        for _ in $(seq 1 20); do
            kill -0 "$BACKEND_PID" 2>/dev/null || break
            sleep 0.5
        done
        if kill -0 "$BACKEND_PID" 2>/dev/null; then
            kill -9 "$BACKEND_PID" 2>/dev/null || true
        fi
    fi
    if [ "$RAGFLOW_OWNED" -eq 1 ]; then
        if ! bash "$PROJECT_ROOT/scripts/ragflow.sh" down; then
            echo -e "${RED}⚠ RAGFlow 未能自動停止，請執行 bash scripts/ragflow.sh status${NC}"
        fi
    fi
    echo -e "${GREEN}✓ 服務已停止${NC}"
    exit "$status"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}🚀 Nova Avatar - 單一入口生產服務${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}❌ 錯誤: 配置檔案不存在: $CONFIG_FILE${NC}"
    show_usage
    exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
    echo -e "${RED}❌ 錯誤: 未檢測到 uv${NC}"
    exit 1
fi

if [ ! -d "$PROJECT_ROOT/.venv" ] && [ -z "${UV_PROJECT_ENVIRONMENT:-}" ]; then
    echo -e "${RED}❌ 錯誤: 虛擬環境 '.venv' 不存在${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} 配置檔案: $CONFIG_FILE"
ensure_web_dist

BACKEND_PORT=$(read_backend_port "$CONFIG_FILE")

clear_port() {
    local port=$1
    local pid
    pid=$(lsof -ti:"$port" 2>/dev/null || true)
    if [ -n "$pid" ]; then
        echo -e "${YELLOW}⚠ 清理埠 $port (PID $pid)${NC}"
        kill $pid 2>/dev/null || true
        sleep 2
        if kill -0 $pid 2>/dev/null; then
            kill -9 $pid 2>/dev/null || true
        fi
    fi
}

if [ "$SYSTEMD_MODE" -eq 0 ]; then
    clear_port "$BACKEND_PORT"
fi

if [ "${NOVA_START_RAGFLOW:-auto}" != 0 ] && \
    { [ "${NOVA_START_RAGFLOW:-auto}" = 1 ] || [ -d "$PROJECT_ROOT/.local/ragflow/upstream/.git" ]; }; then
    echo -e "${BLUE}🔎 啟動 RAGFlow...${NC}"
    if ! bash "$PROJECT_ROOT/scripts/ragflow.sh" is-running >/dev/null 2>&1; then
        RAGFLOW_OWNED=1
    fi
    bash "$PROJECT_ROOT/scripts/ragflow.sh" up
    echo -e "${GREEN}✓${NC} RAGFlow 僅限本機 loopback (http://127.0.0.1:8088)"
else
    echo -e "${YELLOW}RAGFlow 尚未準備或已停用；部署方式見 docs/ragflow.md${NC}"
fi

load_ragflow_env() {
    if [ -f "$PROJECT_ROOT/config/ragflow.env" ]; then
        set -a
        . "$PROJECT_ROOT/config/ragflow.env"
        set +a
    fi
}

cd "$PROJECT_ROOT"

if [ "$SYSTEMD_MODE" -eq 1 ]; then
    load_ragflow_env
    if [ "$RAGFLOW_OWNED" -eq 0 ]; then
        trap - EXIT INT TERM
        exec uv run python src/server/app.py --config "$CONFIG_FILE"
    fi
    uv run python src/server/app.py --config "$CONFIG_FILE" &
    BACKEND_PID=$!
    wait "$BACKEND_PID"
    exit $?
fi

PROTOCOL=$(read_protocol "$CONFIG_FILE")
BACKEND_URL="${PROTOCOL}://localhost:${BACKEND_PORT}"
NETWORK_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
if [ -z "$NETWORK_IP" ]; then
    NETWORK_IP="localhost"
fi
NETWORK_BASE_URL="${PROTOCOL}://${NETWORK_IP}:${BACKEND_PORT}"
mkdir -p "$PROJECT_ROOT/logs"
BACKEND_LOG="$PROJECT_ROOT/logs/start-server.log"

echo -e "${BLUE}🔧 啟動單一入口服務 (:${BACKEND_PORT})...${NC}"
(
    load_ragflow_env
    exec uv run python src/server/app.py --config "$CONFIG_FILE"
) >>"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!
echo -e "${GREEN}✓${NC} 服務程式 PID $BACKEND_PID，日誌: $BACKEND_LOG"

echo -e "${BLUE}⏳ 等待服務就緒...${NC}"
READY=0
for _ in $(seq 1 90); do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo -e "${RED}❌ 服務程式已退出，請檢視 $BACKEND_LOG${NC}"
        exit 1
    fi
    if curl -sk --max-time 2 "$BACKEND_URL/health" 2>/dev/null | grep -q '"ready": true'; then
        READY=1
        break
    fi
    sleep 2
done

if [ "$READY" -ne 1 ]; then
    echo -e "${RED}❌ 等待服務超時，請檢視 $BACKEND_LOG${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} 服務已就緒: $BACKEND_URL"
echo ""
echo -e "${GREEN}🌐 控制台 Local: ${NC}${BACKEND_URL}/"
echo -e "${GREEN}🌐 控制台 Network: ${NC}${NETWORK_BASE_URL}/"
echo -e "${GREEN}🎭 數字人舞台 Local: ${NC}${BACKEND_URL}/stage.html"
echo -e "${GREEN}🎭 數字人舞台 Network: ${NC}${NETWORK_BASE_URL}/stage.html"
echo -e "${YELLOW}單一入口模式運行中（:${BACKEND_PORT}）。按 Ctrl+C 停止服務${NC}"
echo ""

wait "$BACKEND_PID"
