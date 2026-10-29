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
# 配置檔案：相對路徑以呼叫者目錄為準，轉成絕對路徑後再切換目錄
CONFIG_FILE="$(realpath -m -- "${1:-$PROJECT_ROOT/config/config.yaml}")"
# shellcheck source=process-control.sh
. "$PROJECT_ROOT/scripts/process-control.sh"

if [ -f "$PROJECT_ROOT/config/ragflow.env" ]; then
    set -a
    # Private, optional backend-only RAGFlow credentials.
    . "$PROJECT_ROOT/config/ragflow.env"
    set +a
fi

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
    if [ ! -d "$PROJECT_ROOT/.venv" ]; then
        echo -e "${RED}❌ 錯誤: 虛擬環境 '.venv' 不存在${NC}"
        echo -e "${YELLOW}請先執行: uv venv --python 3.10.19${NC}"
        exit 1
    fi

    echo -e "${GREEN}✓${NC} uv 虛擬環境 '.venv' 已找到"

    # 檢查 Python 版本
    PYTHON_VERSION=$(cd "$PROJECT_ROOT" && uv run python --version)
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

# 檢查並清理埠：只停止本專案殘留的後端（寬限期見 process-control.sh），
# 其他程式占用時報錯退出，不誤殺。
check_and_kill_port() {
    local port=8010

    echo -e "${BLUE}🔍 檢查埠 $port 是否被佔用...${NC}"
    nova_clear_port "$port" '*src/server/app.py*' || exit 1
    # 舊後端若曾被強制終止，其 CosyVoice 會成孤兒占用 GPU。
    nova_stop_cosyvoice || true
    echo -e "${GREEN}✓${NC} 埠 $port 可用"
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
        echo -e "${GREEN}🌐 控制台: ${NC}https://localhost:8010（舞台 /stage.html 僅限本機）"
    else
        echo -e "${GREEN}🌐 控制台: ${NC}http://localhost:8010（舞台 /stage.html 僅限本機）"
    fi
    echo -e "${YELLOW}   前端由後端提供 web/dist；未建置時請先執行 bash scripts/start-frontend.sh${NC}"
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
