#!/bin/bash

# Derived from Kedreamix/Linly-Talker-Stream; Apache-2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

# ========================================
# Nova Avatar - 後端啟動指令碼
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
# 配置檔案
CONFIG_FILE="${1:-config/config.yaml}"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}🚀 Nova Avatar - 後端服務啟動${NC}"
echo -e "${BLUE}   即時流式數字人對話系統${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# 顯示使用說明
show_usage() {
    echo -e "${YELLOW}使用方法:${NC}"
    echo -e "${YELLOW}  $0 [配置檔案]${NC}"
    echo ""
    echo -e "${YELLOW}示例:${NC}"
    echo -e "${YELLOW}  $0                                    # 啟動服務（數字人/AI 在網頁設定裡選）${NC}"
    echo -e "${YELLOW}  $0 config/config.yaml                 # 同上，顯式指定預設配置${NC}"
    echo ""
}

# 檢查 uv 是否安裝
check_uv() {
    if ! command -v uv &> /dev/null; then
        echo -e "${RED}❌ 錯誤: 未檢測到 uv${NC}"
        echo -e "${YELLOW}請先安裝 uv 包管理工具${NC}"
        echo -e "${YELLOW}訪問: https://docs.astral.sh/uv/getting-started/installation/${NC}"
        exit 1
    fi
    
    UV_VERSION=$(uv --version)
    echo -e "${GREEN}✓${NC} uv 已安裝: $UV_VERSION"
}

# 檢查 uv 虛擬環境
setup_uv_env() {
    # 檢查 .venv 目錄是否存在
    if [ ! -d ".venv" ]; then
        echo -e "${RED}❌ 錯誤: 虛擬環境 '.venv' 不存在${NC}"
        echo -e "${YELLOW}請先執行: uv venv --python 3.10.19${NC}"
        exit 1
    fi

    echo -e "${GREEN}✓${NC} uv 虛擬環境 '.venv' 已找到"

    # 檢查 Python 版本
    PYTHON_VERSION=$(uv run python --version)
    echo -e "${GREEN}✓${NC} Python 環境: $PYTHON_VERSION"
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

# 檢查並清理埠
check_and_kill_port() {
    local port=8010
    
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

# 啟動後端服務
start_backend() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${GREEN}🎯 啟動後端服務...${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""

    cd "$PROJECT_ROOT"
    
    # 檢查並清理埠
    check_and_kill_port

    if grep -Eq '^[[:space:]]*ssl:[[:space:]]*true([[:space:]]|$)' "$CONFIG_FILE"; then
        echo -e "${GREEN}📡 後端服務地址: ${NC}https://localhost:8010"
    else
        echo -e "${GREEN}📡 後端服務地址: ${NC}http://localhost:8010"
    fi
    echo -e "${YELLOW}💡 按 Ctrl+C 停止服務${NC}"
    echo ""

    uv run python src/server/app.py --config "$CONFIG_FILE"
}

# 主流程
main() {
    check_uv
    setup_uv_env
    check_config
    start_backend
}

# 捕獲中斷訊號
trap 'echo -e "\n${YELLOW}🛑 正在停止後端服務...${NC}"; exit 0' INT TERM

# 執行主流程
main
