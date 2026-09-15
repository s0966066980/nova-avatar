#!/bin/bash

# Derived from Kedreamix/Linly-Talker-Stream; Apache-2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

# ========================================
# Nova Avatar - 環境安裝指令碼
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
# Python 版本
PYTHON_VERSION="3.10.19"
# 預設 Avatar
DEFAULT_AVATAR="${1:-musetalk}"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}🚀 Nova Avatar - 環境安裝指令碼${NC}"
echo -e "${BLUE}   即時流式數字人對話系統${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# 顯示使用說明
show_usage() {
    echo -e "${YELLOW}使用方法:${NC}"
    echo -e "${YELLOW}  $0 [avatar_name]${NC}"
    echo ""
    echo -e "${YELLOW}支援的 Avatar:${NC}"
    echo -e "${YELLOW}  musetalk         # 2D Avatar（預設，MIT code）${NC}"
    echo -e "${YELLOW}  wav2lip          # 2D Avatar（僅限研究／學術／個人用途，不可商用）${NC}"
    echo -e "${YELLOW}  ernerf           # 3D Avatar（神經輻射場）${NC}"
    echo -e "${YELLOW}  talkinggaussian  # 3D Avatar（高斯潑濺）${NC}"
    echo ""
    echo -e "${YELLOW}示例:${NC}"
    echo -e "${YELLOW}  $0                # 安裝 musetalk 環境${NC}"
    echo -e "${YELLOW}  $0 musetalk       # 安裝 musetalk 環境${NC}"
    echo ""
}

# 檢查 Avatar 引數
check_avatar() {
    case "$DEFAULT_AVATAR" in
        wav2lip|musetalk|ernerf|talkinggaussian)
            echo -e "${GREEN}✓${NC} 選擇數字人: $DEFAULT_AVATAR"
            ;;
        *)
            echo -e "${RED}❌ 錯誤: 不支援的數字人 '$DEFAULT_AVATAR'${NC}"
            echo ""
            show_usage
            exit 1
            ;;
    esac
}

# 檢查 uv 是否安裝
check_uv() {
    echo -e "${BLUE}📋 檢查 uv 包管理工具...${NC}"
    
    if ! command -v uv &> /dev/null; then
        echo -e "${RED}❌ 錯誤: 未檢測到 uv${NC}"
        echo -e "${YELLOW}正在安裝 uv...${NC}"
        
        # 自動安裝 uv
        curl -LsSf https://astral.sh/uv/install.sh | sh
        
        # 重新載入 PATH
        export PATH="$HOME/.cargo/bin:$PATH"
        
        if ! command -v uv &> /dev/null; then
            echo -e "${RED}❌ uv 安裝失敗${NC}"
            echo -e "${YELLOW}請手動安裝 uv: https://docs.astral.sh/uv/getting-started/installation/${NC}"
            exit 1
        fi
    fi
    
    UV_VERSION=$(uv --version)
    echo -e "${GREEN}✓${NC} uv 已安裝: $UV_VERSION"
}

# 檢查 Python 版本
check_python() {
    echo -e "${BLUE}📋 檢查 Python 環境...${NC}"
    
    # 檢查系統是否有指定的 Python 版本
    if command -v python${PYTHON_VERSION} &> /dev/null; then
        PYTHON_CMD="python${PYTHON_VERSION}"
    elif command -v python3.10 &> /dev/null; then
        PYTHON_CMD="python3.10"
        echo -e "${YELLOW}⚠ 未找到 Python ${PYTHON_VERSION}，使用 python3.10${NC}"
    elif command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
        PYTHON_VER=$(python3 --version | cut -d' ' -f2)
        echo -e "${YELLOW}⚠ 未找到 Python ${PYTHON_VERSION}，使用系統 Python: ${PYTHON_VER}${NC}"
    else
        echo -e "${RED}❌ 錯誤: 未找到 Python${NC}"
        echo -e "${YELLOW}請安裝 Python 3.10 或更高版本${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✓${NC} Python 命令: $PYTHON_CMD"
}

# 定位 CUDA toolkit（mmcv / CUDA 擴充套件從原始碼編譯時需要 CUDA_HOME）
# torch 2.5.0+cu124 沒有官方 mmcv 預編譯包，mim 會回退到原始碼編譯
setup_cuda_home() {
    echo -e "${BLUE}📋 檢查 CUDA toolkit (CUDA_HOME)...${NC}"

    local candidates=()
    if [ -n "${CUDA_HOME:-}" ]; then
        candidates+=("$CUDA_HOME")
    fi
    candidates+=(
        "$PROJECT_ROOT/.cuda-toolkit"
        "/usr/local/cuda"
        "/usr/local/cuda-12.4"
        "/usr/local/cuda-12.1"
        "/opt/cuda"
    )
    if command -v nvcc &> /dev/null; then
        candidates+=("$(cd "$(dirname "$(command -v nvcc)")/.." && pwd)")
    fi

    local dir
    for dir in "${candidates[@]}"; do
        if [ -x "$dir/bin/nvcc" ]; then
            export CUDA_HOME="$dir"
            export PATH="$CUDA_HOME/bin:$PATH"
            if [ -d "$CUDA_HOME/lib64" ]; then
                export LD_LIBRARY_PATH="$CUDA_HOME/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
            elif [ -d "$CUDA_HOME/lib" ]; then
                export LD_LIBRARY_PATH="$CUDA_HOME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
                # 部分工具只認 lib64；conda/pip 安裝的 toolkit 通常只有 lib
                if [ ! -e "$CUDA_HOME/lib64" ]; then
                    ln -sfn lib "$CUDA_HOME/lib64"
                fi
            fi
            local nvcc_ver
            nvcc_ver="$("$CUDA_HOME/bin/nvcc" --version 2>/dev/null | sed -n 's/.*release \([0-9.]*\).*/\1/p' | head -n1)"
            echo -e "${GREEN}✓${NC} CUDA_HOME=$CUDA_HOME${nvcc_ver:+ (CUDA ${nvcc_ver})}"

            # gcc 13.3 超出 CUDA 12.4 官方支援上限（13.2），允許繼續編譯
            export NVCC_PREPEND_FLAGS="${NVCC_PREPEND_FLAGS:-} -allow-unsupported-compiler"
            # 只編本機 GPU 架構，避免 mmcv 為所有 sm 編譯
            if command -v nvidia-smi &> /dev/null && [ -z "${TORCH_CUDA_ARCH_LIST:-}" ]; then
                local cap
                cap="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -n1 | tr -d ' ')"
                if [ -n "$cap" ]; then
                    export TORCH_CUDA_ARCH_LIST="$cap"
                    echo -e "${GREEN}✓${NC} TORCH_CUDA_ARCH_LIST=$TORCH_CUDA_ARCH_LIST"
                fi
            fi
            return 0
        fi
    done

    echo -e "${RED}❌ 錯誤: 未設定 CUDA_HOME，且找不到 nvcc${NC}"
    echo -e "${YELLOW}mmcv==2.2.0 沒有 torch 2.5 + cu124 的預編譯 wheel，必須從原始碼編譯。${NC}"
    echo -e "${YELLOW}請先安裝 CUDA Toolkit 12.4，或將 toolkit 放到專案目錄 .cuda-toolkit/，然後重試。${NC}"
    echo ""
    echo -e "${YELLOW}示例（conda，無需 root）:${NC}"
    echo -e "${GREEN}  conda create -p .cuda-toolkit -c nvidia cuda-nvcc=12.4 cuda-libraries-dev=12.4 --yes${NC}"
    echo -e "${GREEN}  export CUDA_HOME=\"\$PWD/.cuda-toolkit\"${NC}"
    return 1
}

# 建立虛擬環境
create_venv() {
    echo -e "${BLUE}📦 建立虛擬環境...${NC}"
    
    cd "$PROJECT_ROOT"
    
    # 如果虛擬環境已存在，詢問是否重新建立
    if [ -d ".venv" ]; then
        echo -e "${YELLOW}⚠ 虛擬環境 '.venv' 已存在${NC}"
        read -p "是否重新建立？(y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo -e "${YELLOW}🗑 刪除現有虛擬環境...${NC}"
            rm -rf .venv
        else
            echo -e "${GREEN}✓${NC} 使用現有虛擬環境"
            return
        fi
    fi
    
    echo -e "${YELLOW}📦 建立新的虛擬環境...${NC}"
    uv venv --python "$PYTHON_CMD"
    
    echo -e "${GREEN}✓${NC} 虛擬環境建立完成"
}

# 安裝核心依賴
install_core_deps() {
    echo -e "${BLUE}📦 安裝核心依賴...${NC}"
    
    cd "$PROJECT_ROOT"
    
    echo -e "${YELLOW}📦 正在安裝基礎依賴...${NC}"
    uv sync --extra vad
    
    echo -e "${GREEN}✓${NC} 核心依賴安裝完成（含 Silero / WebRTC VAD）"
}

# 安裝 Avatar 模組
install_avatar() {
    echo -e "${BLUE}📦 安裝 $DEFAULT_AVATAR Avatar...${NC}"
    
    cd "$PROJECT_ROOT"
    
    # 檢查 Avatar 目錄是否存在
    AVATAR_PATH="src/avatars/$DEFAULT_AVATAR/"
    if [ ! -d "$AVATAR_PATH" ]; then
        echo -e "${RED}❌ 錯誤: Avatar 目錄不存在: $AVATAR_PATH${NC}"
        exit 1
    fi
    
    echo -e "${YELLOW}📦 正在安裝 $DEFAULT_AVATAR 模組...${NC}"
    
    # 特殊處理：MuseTalk 需要額外的依賴
    if [ "$DEFAULT_AVATAR" = "musetalk" ]; then
        echo -e "${YELLOW}📦 安裝 MuseTalk 依賴...${NC}"
        setup_cuda_home
        uv pip install chumpy==0.70 --no-build-isolation
        uv pip install ninja
        uv pip install -e "$AVATAR_PATH"
        uv run mim install mmengine
        FORCE_CUDA=1 MMCV_WITH_OPS=1 uv run mim install mmcv==2.2.0 --no-build-isolation
        uv run mim install mmdet==3.1.0
        uv run mim install mmpose==1.3.2
        
        # 執行後處理指令碼
        echo -e "${YELLOW}📦 執行 MuseTalk 後處理指令碼...${NC}"
        bash scripts/post_musetalk_install.sh
        
    # 特殊處理：TalkingGaussian 需要額外的子模組
    elif [ "$DEFAULT_AVATAR" = "talkinggaussian" ]; then
        setup_cuda_home
        uv pip install -e "$AVATAR_PATH"
        echo -e "${YELLOW}📦 安裝 TalkingGaussian 子模組...${NC}"
        uv pip install -e src/avatars/talkinggaussian/submodules/diff-gaussian-rasterization/ --no-build-isolation
        uv pip install -e src/avatars/talkinggaussian/submodules/simple-knn/ --no-build-isolation
        uv pip install -e src/avatars/talkinggaussian/gridencoder/ --no-build-isolation
        
    # 其他 Avatar：標準安裝
    else
        uv pip install -e "$AVATAR_PATH"
    fi
    
    echo -e "${GREEN}✓${NC} $DEFAULT_AVATAR 數字人安裝完成"
}

# 安裝前端依賴
install_frontend_deps() {
    echo -e "${BLUE}📦 安裝前端依賴...${NC}"
    
    # 檢查 Node.js
    if ! command -v node &> /dev/null; then
        echo -e "${RED}❌ 錯誤: 未檢測到 Node.js${NC}"
        echo -e "${YELLOW}請先安裝 Node.js 16 或更高版本${NC}"
        echo -e "${YELLOW}訪問: https://nodejs.org/${NC}"
        exit 1
    fi
    
    NODE_VERSION=$(node --version)
    echo -e "${GREEN}✓${NC} Node.js 環境: $NODE_VERSION"
    
    # 檢查 npm
    if ! command -v npm &> /dev/null; then
        echo -e "${RED}❌ 錯誤: 未檢測到 npm${NC}"
        exit 1
    fi
    
    NPM_VERSION=$(npm --version)
    echo -e "${GREEN}✓${NC} npm 版本: $NPM_VERSION"
    
    cd "$PROJECT_ROOT/web"
    
    echo -e "${YELLOW}📦 正在安裝前端依賴...${NC}"
    npm install
    
    echo -e "${GREEN}✓${NC} 前端依賴安裝完成"
    
    cd "$PROJECT_ROOT"
}

# 驗證安裝
verify_installation() {
    echo -e "${BLUE}🔍 驗證安裝...${NC}"
    
    cd "$PROJECT_ROOT"
    
    # 檢查虛擬環境
    if [ ! -d ".venv" ]; then
        echo -e "${RED}❌ 虛擬環境不存在${NC}"
        return 1
    fi
    
    # 檢查 Python 版本
    PYTHON_VERSION_INSTALLED=$(uv run python --version)
    echo -e "${GREEN}✓${NC} Python 環境: $PYTHON_VERSION_INSTALLED"
    
    # 檢查配置檔案
    CONFIG_FILE="config/config_${DEFAULT_AVATAR}.yaml"
    if [ -f "$CONFIG_FILE" ]; then
        echo -e "${GREEN}✓${NC} 配置檔案: $CONFIG_FILE"
    else
        echo -e "${YELLOW}⚠ 配置檔案不存在: $CONFIG_FILE${NC}"
    fi
    
    # 檢查前端
    if [ -d "web/node_modules" ]; then
        echo -e "${GREEN}✓${NC} 前端依賴已安裝"
    else
        echo -e "${YELLOW}⚠ 前端依賴未安裝${NC}"
    fi
    
    echo -e "${GREEN}✓${NC} 安裝驗證完成"
}

# 顯示下一步操作
show_next_steps() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${GREEN}✅ 環境安裝完成！${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    echo -e "${YELLOW}📋 下一步操作:${NC}"
    echo ""
    echo -e "${YELLOW}1. 配置 API Key（如果使用線上 LLM）:${NC}"
    echo -e "${GREEN}   export DASHSCOPE_API_KEY=\"your_api_key_here\"${NC}"
    echo ""
    echo -e "${YELLOW}2. 啟動服務:${NC}"
    echo -e "${GREEN}   bash scripts/start-all.sh config/config_${DEFAULT_AVATAR}.yaml${NC}"
    echo ""
    echo -e "${YELLOW}3. 或者分步啟動:${NC}"
    echo -e "${GREEN}   # 啟動後端${NC}"
    echo -e "${GREEN}   bash scripts/start-backend.sh config/config_${DEFAULT_AVATAR}.yaml${NC}"
    echo -e "${GREEN}   # 啟動前端（新終端）${NC}"
    echo -e "${GREEN}   bash scripts/start-frontend.sh config/config_${DEFAULT_AVATAR}.yaml${NC}"
    echo ""
    echo -e "${YELLOW}4. 訪問應用:${NC}"
    echo -e "${GREEN}   http://localhost:3000${NC}"
    echo ""
}

# 主流程
main() {
    check_avatar
    check_uv
    check_python
    create_venv
    install_core_deps
    install_avatar
    install_frontend_deps
    verify_installation
    show_next_steps
}

# 捕獲中斷訊號
trap 'echo -e "\n${YELLOW}🛑 安裝被中斷${NC}"; exit 1' INT TERM

# 執行主流程
main
