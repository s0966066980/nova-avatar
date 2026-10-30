#!/bin/bash

# Derived from Kedreamix/Linly-Talker-Stream; Apache-2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

# ========================================
# Nova Avatar - 全棧啟動指令碼
# 建置前端（web/dist），再啟動後端；控制台與舞台由後端同源提供
# 與分開執行 start-frontend.sh（建置）+ start-backend.sh 同一套服務
# ========================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$PROJECT_ROOT/web"
# 相對路徑以呼叫者目錄為準；轉成絕對路徑，切換目錄後前後端讀到同一檔案
CONFIG_FILE="$(realpath -m -- "${1:-$PROJECT_ROOT/config/config.yaml}")"
# shellcheck source=process-control.sh
. "$PROJECT_ROOT/scripts/process-control.sh"
BACKEND_PID=""
# 後端以 setsid 啟動，自成程序群組；結束時整組終止，uv 子程序不會成孤兒。
BACKEND_PGID=""
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
    # 收尾期間不再被 Ctrl+C 打斷，避免留下孤兒程序。
    trap '' INT TERM
    echo ""
    echo -e "${YELLOW}🛑 正在停止所有服務...${NC}"
    if [ -n "$BACKEND_PGID" ]; then
        # 先 SIGTERM 讓後端關閉連線、llama-server 與模型服務，寬限期後才 SIGKILL。
        if ! nova_stop_group "$BACKEND_PGID"; then
            echo -e "${RED}⚠ 後端程序群組 $BACKEND_PGID 未能停止，請手動處理${NC}"
        fi
    fi
    # 後端被強制終止時 atexit 不會執行；確認 CosyVoice、Fun-ASR-Nano 也已停止。
    nova_stop_model_servers || true
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

if ! command -v setsid >/dev/null 2>&1; then
    echo -e "${RED}❌ 錯誤: 需要 setsid（util-linux）${NC}"
    exit 1
fi

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    echo -e "${RED}❌ 錯誤: 需要 Node.js / npm${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} 配置檔案: $CONFIG_FILE"

# 建置與帶起 RAGFlow 前先確認 8010：只停止本專案殘留的後端（與其孤兒
# CosyVoice、Fun-ASR-Nano）；其他程式占用時報錯退出，不誤殺。
nova_clear_port 8010 '*src/server/app.py*' || exit 1
nova_stop_model_servers || true

cd "$FRONTEND_DIR"
if [ ! -d node_modules ]; then
    echo -e "${YELLOW}📦 安裝前端依賴...${NC}"
    npm install
fi
echo -e "${BLUE}🔨 建置前端...${NC}"
export CONFIG_FILE
env -u NOVA_RAGFLOW_API_KEY -u NOVA_RAGFLOW_URL VITE_CONFIG_QUIET=1 \
    npm --silent run build -- --logLevel warn
echo -e "${GREEN}✓${NC} 前端已建置: $FRONTEND_DIR/dist"
cd "$PROJECT_ROOT"

# 已完成本機 RAGFlow 準備後，日常啟動一併帶起其獨立服務。
# 已在執行的 Compose 專案或嵌入服務屬於外部生命週期，不由本腳本停止。
if [ "${NOVA_START_RAGFLOW:-auto}" != 0 ] && \
    { [ "${NOVA_START_RAGFLOW:-auto}" = 1 ] || [ -d "$PROJECT_ROOT/.local/ragflow/upstream/.git" ]; }; then
    echo -e "${BLUE}🔎 啟動 RAGFlow...${NC}"
    # RAGFlow 失敗不阻擋數字人：記錄警告後照常啟動，只是暫無知識庫檢索。
    # Docker 啟動時可能自動恢復既有容器，必須在這之後判定服務所有權。
    if ! bash "$PROJECT_ROOT/scripts/ragflow.sh" ensure-docker; then
        echo -e "${YELLOW}⚠ Docker 未就緒，略過 RAGFlow；數字人照常啟動（無知識庫檢索）${NC}"
    else
        if ! bash "$PROJECT_ROOT/scripts/ragflow.sh" is-running >/dev/null 2>&1; then
            RAGFLOW_OWNED=1
        fi
        if bash "$PROJECT_ROOT/scripts/ragflow.sh" up; then
            RAGFLOW_STARTED=1
            echo -e "${GREEN}✓${NC} RAGFlow 管理頁: http://127.0.0.1:8088"
        else
            echo -e "${YELLOW}⚠ RAGFlow 未能就緒；數字人照常啟動（無知識庫檢索），請執行 bash scripts/ragflow.sh status 檢查${NC}"
            if [ "$RAGFLOW_OWNED" -eq 1 ]; then
                # 收掉這次帶起的部分服務，不讓半啟動的容器占用資源。
                RAGFLOW_OWNED=0
                if ! bash "$PROJECT_ROOT/scripts/ragflow.sh" down; then
                    echo -e "${RED}⚠ RAGFlow 未能自動停止，請執行 bash scripts/ragflow.sh status${NC}"
                fi
            fi
        fi
    fi
else
    echo -e "${YELLOW}RAGFlow 尚未準備或已停用；部署方式見 docs/ragflow.md${NC}"
fi

PROTOCOL=$(read_protocol "$CONFIG_FILE")
BACKEND_URL="${PROTOCOL}://localhost:8010"
NETWORK_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -z "$NETWORK_IP" ]; then
    NETWORK_IP="localhost"
fi
NETWORK_BACKEND_URL="${PROTOCOL}://${NETWORK_IP}:8010"
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
    # 非互動腳本的背景子程序不是群組領頭，setsid 不會 fork：PID 即 PGID。
    exec setsid uv run python src/server/app.py --config "$CONFIG_FILE"
) >>"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!
BACKEND_PGID=$BACKEND_PID
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
echo -e "${GREEN}🌐 控制台 Local: ${NC}$BACKEND_URL"
echo -e "${GREEN}🌐 控制台 Network: ${NC}$NETWORK_BACKEND_URL"
if [ "$PROTOCOL" != https ]; then
    echo -e "${YELLOW}   登入 cookie 為 Secure，區網連入控制台需在配置啟用 ssl: true${NC}"
fi
echo -e "${GREEN}🎭 數字人舞台 Local: ${NC}$BACKEND_URL/stage.html"
echo -e "${YELLOW}   舞台只在本機開啟（其他電腦會被拒絕）；場域全螢幕請執行 bash scripts/start-kiosk.sh${NC}"
if [ "$RAGFLOW_STARTED" -eq 1 ]; then
    echo -e "${GREEN}📚 RAGFlow 管理頁 Local: ${NC}http://127.0.0.1:8088"
fi
echo -e "${YELLOW}控制台與舞台已分流，可同時連線；設定仍在控制台。按 Ctrl+C 停止全部服務${NC}"
echo ""

# 後端在前景期間保持執行；後端自行結束時以其結束碼離開。
BACKEND_STATUS=0
wait "$BACKEND_PID" || BACKEND_STATUS=$?
BACKEND_PID=""
if [ "$BACKEND_STATUS" -ne 0 ]; then
    echo -e "${RED}❌ 後端程式已結束（代碼 $BACKEND_STATUS），請檢視 $BACKEND_LOG${NC}"
fi
exit "$BACKEND_STATUS"
