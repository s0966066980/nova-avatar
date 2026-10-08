#!/usr/bin/env bash
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

# Build the CUDA backend that PyPI's ARM64 CTranslate2 wheel omits.
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
export PATH="$HOME/.local/bin:$PATH"
export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
export PATH="$CUDA_HOME/bin:$PATH"
CT2_SOURCE="$PROJECT_ROOT/.local/jetson/CTranslate2"
export CTRANSLATE2_ROOT="$PROJECT_ROOT/.local/jetson/ctranslate2"
CT2_JOBS="${NOVA_BUILD_JOBS:-8}"

test "$(uname -m)" = aarch64 || { echo 'This build is for ARM64 Jetson.'; exit 1; }
test -x "$CUDA_HOME/bin/nvcc" || { echo 'CUDA Toolkit / nvcc is required.'; exit 1; }
test -x .venv/bin/python || { echo 'Create the ARM64 .venv first.'; exit 1; }
uv pip install --python .venv/bin/python pybind11==2.11.1 wheel setuptools==69.5.1 'numpy<2' pyyaml
if [ ! -d "$CT2_SOURCE/.git" ]; then
    mkdir -p "$PROJECT_ROOT/.local/jetson"
    git clone --depth 1 --branch v4.8.2 --recursive \
        https://github.com/OpenNMT/CTranslate2.git "$CT2_SOURCE"
fi
test "$(git -C "$CT2_SOURCE" rev-parse HEAD)" = d44d2d069eb88c7b7804da864c10c201501cb4a9
cmake -S "$CT2_SOURCE" -B "$CT2_SOURCE/build" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$CTRANSLATE2_ROOT" \
    -DWITH_MKL=OFF -DWITH_OPENBLAS=ON -DOPENMP_RUNTIME=COMP \
    -DWITH_CUDA=ON -DWITH_CUDNN=ON -DCUDA_ARCH_LIST=8.7 \
    -DCUDA_TOOLKIT_ROOT_DIR="$CUDA_HOME" -DBUILD_CLI=OFF
cmake --build "$CT2_SOURCE/build" -j "$CT2_JOBS"
cmake --install "$CT2_SOURCE/build"
(
    cd "$CT2_SOURCE/python"
    # Embed the local library location so normal uv run needs no LD_LIBRARY_PATH.
    export LDFLAGS="${LDFLAGS:-} -Wl,-rpath,$CTRANSLATE2_ROOT/lib"
    export CMAKE_BUILD_PARALLEL_LEVEL="$CT2_JOBS"
    "$PROJECT_ROOT/.venv/bin/python" setup.py bdist_wheel
)
mkdir -p "$PROJECT_ROOT/.local/jetson/wheels"
cp "$CT2_SOURCE"/python/dist/*.whl "$PROJECT_ROOT/.local/jetson/wheels/"
uv pip install --python .venv/bin/python --reinstall --no-deps "$PROJECT_ROOT/.local/jetson/wheels/"*.whl
.venv/bin/python -c 'import ctranslate2; assert ctranslate2.get_cuda_device_count() > 0; assert "float16" in ctranslate2.get_supported_compute_types("cuda"); print("CTranslate2 CUDA FP16 ready")'
