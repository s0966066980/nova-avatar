#!/bin/bash

# Derived from Kedreamix/Linly-Talker-Stream; Apache-2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

# ========================================
# Nova Avatar - 前端建置指令碼
# 即時流式數字人對話系統
# 預設建置 web/dist，由後端（8010）同源提供控制台與舞台；
# --dev 啟動只綁本機的 Vite 開發伺服器，僅供開發。
# ========================================

set -e  # 遇到錯誤立即退出

# 顏色定義
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 專案路徑
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# 前端目錄
FRONTEND_DIR="$PROJECT_ROOT/web"
# 開發模式
DEV_MODE=0
if [ "${1:-}" = "--dev" ]; then
    DEV_MODE=1
    shift
fi
# 配置檔案：相對路徑以呼叫者目錄為準，轉成絕對路徑後再切換目錄
CONFIG_FILE="$(realpath -m -- "${1:-$PROJECT_ROOT/config/config.yaml}")"
# shellcheck source=process-control.sh
. "$PROJECT_ROOT/scripts/process-control.sh"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}🚀 Nova Avatar - 前端建置${NC}"
echo -e "${BLUE}   即時流式數字人對話系統${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# 顯示使用說明
show_usage() {
    echo -e "${YELLOW}使用方法:${NC}"
    echo -e "${YELLOW}  $0 [--dev] [配置檔案]${NC}"
    echo ""
    echo -e "${YELLOW}示例:${NC}"
    echo -e "${YELLOW}  $0                                    # 建置 web/dist，由後端提供${NC}"
    echo -e "${YELLOW}  $0 config/config.yaml                 # 同上${NC}"
    echo -e "${YELLOW}  $0 --dev config/config.yaml           # 本機 Vite 開發伺服器（僅供開發）${NC}"
    echo ""
}

# 檢查配置檔案
check_config() {
    if [ ! -f "$CONFIG_FILE" ]; then
        echo -e "${RED}❌ 錯誤: 配置檔案不存在: $CONFIG_FILE${NC}"
        echo ""
        show_usage
        exit 1
    fi

    echo -e "${GREEN}✓${NC} 配置檔案: $CONFIG_FILE"
}

# 檢查 uv 環境（如果存在）
show_uv_env() {
    if command -v uv &> /dev/null; then
        if [ -d "$PROJECT_ROOT/.venv" ]; then
            PYTHON_VERSION=$(cd "$PROJECT_ROOT" && uv run python --version 2>/dev/null || echo "未知")
            echo -e "${GREEN}✓${NC} uv 虛擬環境: $PYTHON_VERSION"
        fi
    fi
}

# 檢查 Node.js 是否安裝
check_node() {
    if ! command -v node &> /dev/null; then
        echo -e "${RED}❌ 錯誤: 未檢測到 Node.js${NC}"
        echo -e "${YELLOW}請先安裝 Node.js 16 或更高版本${NC}"
        echo -e "${YELLOW}訪問: https://nodejs.org/${NC}"
        exit 1
    fi

    NODE_VERSION=$(node --version)
    echo -e "${GREEN}✓${NC} Node.js 環境: $NODE_VERSION"
}

# 檢查 npm 是否安裝
check_npm() {
    if ! command -v npm &> /dev/null; then
        echo -e "${RED}❌ 錯誤: 未檢測到 npm${NC}"
        echo -e "${YELLOW}npm 通常隨 Node.js 一起安裝${NC}"
        exit 1
    fi

    NPM_VERSION=$(npm --version)
    echo -e "${GREEN}✓${NC} npm 版本: $NPM_VERSION"
}

# 檢查並安裝依賴
install_dependencies() {
    cd "$FRONTEND_DIR"

    if [ ! -d "node_modules" ]; then
        echo -e "${YELLOW}📦 未檢測到 node_modules，正在安裝依賴...${NC}"
        npm install
        echo -e "${GREEN}✓${NC} 依賴安裝完成"
    else
        echo -e "${GREEN}✓${NC} node_modules 已存在"

        # 檢查 package.json 是否有更新
        if [ package.json -nt node_modules ]; then
            echo -e "${YELLOW}📦 檢測到 package.json 已更新，正在更新依賴...${NC}"
            npm install
            echo -e "${GREEN}✓${NC} 依賴更新完成"
        else
            echo -e "${GREEN}✓${NC} 依賴已是最新"
        fi
    fi
}

# 檢查並清理埠：只停止本專案殘留的 Vite 開發伺服器（寬限期見
# process-control.sh），其他程式占用時報錯退出，不誤殺。
check_and_kill_port() {
    local port=3000

    echo -e "${BLUE}🔍 檢查埠 $port 是否被佔用...${NC}"
    nova_clear_port "$port" '*node_modules/*vite*' || exit 1
    echo -e "${GREEN}✓${NC} 埠 $port 可用"
}

# 建置正式前端：後端只提供 web/dist
build_frontend() {
    echo ""
    echo -e "${BLUE}🔨 建置前端...${NC}"
    cd "$FRONTEND_DIR"
    export CONFIG_FILE
    npm run build
    if grep -Eq '^[[:space:]]*ssl:[[:space:]]*true([[:space:]]|$)' "$CONFIG_FILE"; then
        PROTOCOL=https
    else
        PROTOCOL=http
    fi
    echo ""
    echo -e "${GREEN}✓${NC} 前端已建置: $FRONTEND_DIR/dist"
    echo -e "${GREEN}🌐 啟動後端後開啟控制台: ${NC}${PROTOCOL}://localhost:8010"
    echo -e "${YELLOW}   舞台 ${PROTOCOL}://localhost:8010/stage.html 僅限本機開啟${NC}"
}

# 啟動 Vite 開發伺服器（只綁本機，API 代理到後端）
start_vite() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${GREEN}🎯 啟動 Vite 開發伺服器（僅供開發）...${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""

    cd "$FRONTEND_DIR"
    
    # 檢查並清理埠
    check_and_kill_port

    if grep -Eq '^[[:space:]]*ssl:[[:space:]]*true([[:space:]]|$)' "$CONFIG_FILE"; then
        echo -e "${GREEN}🌐 開發頁面: ${NC}https://127.0.0.1:3000"
    else
        echo -e "${GREEN}🌐 開發頁面: ${NC}http://127.0.0.1:3000"
    fi
    echo -e "${YELLOW}   正式使用請建置後開啟後端 8010；開發伺服器不對區網開放${NC}"
    echo -e "${YELLOW}💡 按 Ctrl+C 停止服務${NC}"
    echo ""

    # Vite 讀同一份配置的埠與 SSL（絕對路徑）
    export CONFIG_FILE
    echo -e "${GREEN}🔧 使用配置: ${CONFIG_FILE}${NC}"
    echo ""
    
    npm run dev
}

# 主流程
main() {
    check_config
    show_uv_env
    check_node
    check_npm
    install_dependencies
    if [ "$DEV_MODE" -eq 1 ]; then
        start_vite
    else
        build_frontend
    fi
}

# 捕獲中斷訊號
trap 'echo -e "\n${YELLOW}🛑 正在停止前端服務...${NC}"; exit 0' INT TERM

# 執行主流程
main
