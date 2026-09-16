#!/bin/bash

# Derived from Kedreamix/Linly-Talker-Stream; Apache-2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

# ========================================
# Nova Avatar - 全棧啟動指令碼
# 與分開執行 start-backend.sh + start-frontend.sh 同一套服務
# ========================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$PROJECT_ROOT/web"
CONFIG_FILE="${1:-config/config.yaml}"
BACKEND_PID=""
RAGFLOW_OWNED=0
RAGFLOW_STARTED=0

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}🚀 Nova Avatar - 全棧服務啟動${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

show_usage() {
    echo -e "${YELLOW}使用方法:${NC}"
    echo -e "${YELLOW}  $0${NC}"
    echo -e "${YELLOW}  $0 config/config.yaml${NC}"
    echo ""
}

read_protocol() {
    if grep -Eq '^[[:space:]]*ssl:[[:space:]]*true([[:space:]]|$)' "$1"; then
        echo https
    else
        echo http
    fi
}

cleanup() {
    local status=$?
    trap - EXIT
    echo ""
    echo -e "${YELLOW}🛑 正在停止所有服務...${NC}"
    if [ -n "$BACKEND_PID" ]; then
        kill "$BACKEND_PID" 2>/dev/null || true
        sleep 1
        if kill -0 "$BACKEND_PID" 2>/dev/null; then
            kill -9 "$BACKEND_PID" 2>/dev/null || true
        fi
        # uv 子程式可能還在
        pkill -P "$BACKEND_PID" 2>/dev/null || true
    fi
    if [ "$RAGFLOW_OWNED" -eq 1 ]; then
        if ! bash "$PROJECT_ROOT/scripts/ragflow.sh" down; then
            echo -e "${RED}⚠ RAGFlow 未能自動停止，請執行 bash scripts/ragflow.sh status${NC}"
        fi
    fi
    echo -e "${GREEN}✓ 所有服務已停止${NC}"
    exit "$status"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}❌ 錯誤: 配置檔案不存在: $CONFIG_FILE${NC}"
    show_usage
    exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
    echo -e "${RED}❌ 錯誤: 未檢測到 uv${NC}"
    exit 1
fi

if [ ! -d "$PROJECT_ROOT/.venv" ]; then
    echo -e "${RED}❌ 錯誤: 虛擬環境 '.venv' 不存在${NC}"
    exit 1
fi

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    echo -e "${RED}❌ 錯誤: 需要 Node.js / npm${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} 配置檔案: $CONFIG_FILE"

cd "$FRONTEND_DIR"
if [ ! -d node_modules ]; then
    echo -e "${YELLOW}📦 安裝前端依賴...${NC}"
    npm install
fi
cd "$PROJECT_ROOT"

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

clear_port 8010
clear_port 3000

# 已完成本機 RAGFlow 準備後，日常啟動一併帶起其獨立服務。
# 已在執行的 Compose 專案或嵌入服務屬於外部生命週期，不由本腳本停止。
if [ "${NOVA_START_RAGFLOW:-auto}" != 0 ] && \
    { [ "${NOVA_START_RAGFLOW:-auto}" = 1 ] || [ -d "$PROJECT_ROOT/.local/ragflow/upstream/.git" ]; }; then
    echo -e "${BLUE}🔎 啟動 RAGFlow...${NC}"
    if ! bash "$PROJECT_ROOT/scripts/ragflow.sh" is-running >/dev/null 2>&1; then
        RAGFLOW_OWNED=1
    fi
    bash "$PROJECT_ROOT/scripts/ragflow.sh" up
    RAGFLOW_STARTED=1
    echo -e "${GREEN}✓${NC} RAGFlow 管理頁: http://127.0.0.1:8088"
else
    echo -e "${YELLOW}RAGFlow 尚未準備或已停用；部署方式見 docs/ragflow.md${NC}"
fi

PROTOCOL=$(read_protocol "$CONFIG_FILE")
BACKEND_URL="${PROTOCOL}://localhost:8010"
FRONTEND_URL="${PROTOCOL}://localhost:3000"
NETWORK_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -z "$NETWORK_IP" ]; then
    NETWORK_IP="localhost"
fi
NETWORK_FRONTEND_URL="${PROTOCOL}://${NETWORK_IP}:3000"
mkdir -p "$PROJECT_ROOT/logs"
BACKEND_LOG="$PROJECT_ROOT/logs/start-all-backend.log"

echo -e "${BLUE}🔧 啟動後端...${NC}"
cd "$PROJECT_ROOT"
(
    if [ -f "$PROJECT_ROOT/config/ragflow.env" ]; then
        set -a
        . "$PROJECT_ROOT/config/ragflow.env"
        set +a
    fi
    exec uv run python src/server/app.py --config "$CONFIG_FILE"
) >>"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!
echo -e "${GREEN}✓${NC} 後端程式 PID $BACKEND_PID，日誌: $BACKEND_LOG"

echo -e "${BLUE}⏳ 等待後端就緒（首次載入數字人可能需要一兩分鐘）...${NC}"
READY=0
for i in $(seq 1 90); do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo -e "${RED}❌ 後端程式已退出，請檢視 $BACKEND_LOG${NC}"
        exit 1
    fi
    if curl -sk --max-time 2 "$BACKEND_URL/health" 2>/dev/null | grep -q '"ready": true'; then
        READY=1
        break
    fi
    sleep 2
done

if [ "$READY" -ne 1 ]; then
    echo -e "${RED}❌ 等待後端超時，請檢視 $BACKEND_LOG${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} 後端已就緒: $BACKEND_URL"
echo ""
echo -e "${GREEN}🌐 控制台 Local: ${NC}$FRONTEND_URL"
echo -e "${GREEN}🌐 控制台 Network: ${NC}$NETWORK_FRONTEND_URL"
echo -e "${GREEN}🎭 數字人舞台 Local: ${NC}$FRONTEND_URL/stage.html"
echo -e "${GREEN}🎭 數字人舞台 Network: ${NC}$NETWORK_FRONTEND_URL/stage.html"
if [ "$RAGFLOW_STARTED" -eq 1 ]; then
    echo -e "${GREEN}📚 RAGFlow 管理頁 Local: ${NC}http://127.0.0.1:8088"
fi
echo -e "${YELLOW}控制台與舞台已分流，可同時連線；設定仍在控制台。按 Ctrl+C 停止全部服務${NC}"
echo ""

cd "$FRONTEND_DIR"
CONFIG_BASENAME=$(basename "$CONFIG_FILE" .yaml)
export CONFIG_FILE="$CONFIG_BASENAME.yaml"
export VITE_CONFIG_QUIET=1
env -u NOVA_RAGFLOW_API_KEY -u NOVA_RAGFLOW_URL npm --silent run dev -- --logLevel warn
