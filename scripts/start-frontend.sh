#!/bin/bash

# Derived from Kedreamix/Linly-Talker-Stream; Apache-2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

# ========================================
# Nova Avatar - 前端啟動指令碼
# 即時流式數字人對話系統
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
# 配置檔案
CONFIG_FILE="${1:-config/config.yaml}"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}🚀 Nova Avatar - 前端服務啟動${NC}"
echo -e "${BLUE}   即時流式數字人對話系統${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# 顯示使用說明
show_usage() {
    echo -e "${YELLOW}使用方法:${NC}"
    echo -e "${YELLOW}  $0 [配置檔案]${NC}"
    echo ""
    echo -e "${YELLOW}示例:${NC}"
    echo -e "${YELLOW}  $0                                    # 啟動前端（埠/SSL 讀 config/config.yaml）${NC}"
    echo -e "${YELLOW}  $0 config/config.yaml                 # 同上${NC}"
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
        if [ -d ".venv" ]; then
            PYTHON_VERSION=$(uv run python --version 2>/dev/null || echo "未知")
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

# 檢查並清理埠
check_and_kill_port() {
    local port=3000
    
    echo -e "${BLUE}🔍 檢查埠 $port 是否被佔用...${NC}"
    
    # 查詢佔用埠的程式
    local pid=$(lsof -ti:$port 2>/dev/null)
    
    if [ -n "$pid" ]; then
        echo -e "${YELLOW}⚠ 埠 $port 被程式 $pid 佔用${NC}"
        
        # 顯示程式資訊
        local process_info=$(ps -p $pid -o pid,ppid,cmd --no-headers 2>/dev/null)
        if [ -n "$process_info" ]; then
            echo -e "${YELLOW}程式資訊: $process_info${NC}"
        fi
        
        echo -e "${YELLOW}正在終止佔用埠的程式...${NC}"
        kill $pid 2>/dev/null
        
        # 等待程式結束
        sleep 2
        
        # 檢查程式是否還存在
        if kill -0 $pid 2>/dev/null; then
            echo -e "${YELLOW}程式未響應，強制終止...${NC}"
            kill -9 $pid 2>/dev/null
            sleep 1
        fi
        
        # 再次檢查埠
        local new_pid=$(lsof -ti:$port 2>/dev/null)
        if [ -n "$new_pid" ]; then
            echo -e "${RED}❌ 無法清理埠 $port，請手動處理${NC}"
            exit 1
        else
            echo -e "${GREEN}✓${NC} 埠 $port 已清理"
        fi
    else
        echo -e "${GREEN}✓${NC} 埠 $port 可用"
    fi
}

# 啟動 Vite 開發伺服器
start_vite() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${GREEN}🎯 啟動 Vite 開發伺服器...${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""

    cd "$FRONTEND_DIR"
    
    # 檢查並清理埠
    check_and_kill_port

    if grep -Eq '^[[:space:]]*ssl:[[:space:]]*true([[:space:]]|$)' "$CONFIG_FILE"; then
        echo -e "${GREEN}🌐 請開啟: ${NC}https://localhost:3000"
        echo -e "${YELLOW}   （配置啟用了 SSL，不要用 http://，也不要開啟 8010）${NC}"
    else
        echo -e "${GREEN}🌐 請開啟: ${NC}http://localhost:3000"
        echo -e "${YELLOW}   不要開啟 8010，那是後端 API，不是這個介面${NC}"
    fi
    echo -e "${YELLOW}💡 按 Ctrl+C 停止服務${NC}"
    echo ""

    # 從配置檔案路徑提取檔名（不含路徑和副檔名）
    CONFIG_BASENAME=$(basename "$CONFIG_FILE" .yaml)
    
    # 設定環境變數指定配置檔案
    export CONFIG_FILE="$CONFIG_BASENAME.yaml"
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
    start_vite
}

# 捕獲中斷訊號
trap 'echo -e "\n${YELLOW}🛑 正在停止前端服務...${NC}"; exit 0' INT TERM

# 執行主流程
main
