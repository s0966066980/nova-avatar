<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 第 1 階段 CUDA 補驗：鎖定依賴與實際 GPU 運算

執行狀態：passed（鎖定安裝、依賴相容性與實際 GPU 運算均通過）
理解確認：pending
日期：2026-11-17；命令時間為 UTC

## 已確認的範圍變更

使用者指定「這版我只做有 cuda 的」。本版後續 Python 驗證統一使用 CUDA
PyTorch 與可用 GPU，取消先前提議的 CPU-only 路線。既有 CPU 紀錄保留作歷史
追查，不計為本版 CUDA 驗收。

本次是同一階段的獨立 CUDA 補驗，不覆蓋前次紀錄。前端依賴準備結果沿用
[前一份紀錄](../stage-01-20261117T133233Z/README.md)，沒有重跑前端測試。

## 來源與環境

- commit：`b1afdce7429eb166d3d36f6e233a07a14fbc2d52`。
- 沿用前次 `git archive` 的乾淨來源快照，重新核對目前 HEAD、已追蹤差異及
  pyproject、lock、workflow hash，再準備新的隔離環境。
- 來源與虛擬環境路徑、來源識別、輸入檔 hash、起迄時間在 [manifest.json](manifest.json)。
- 未修改原專案 `.venv`、現有 workflow 或鎖檔。
- 本輪只安裝現有 `dev`、`ci`、`vad` 測試依賴；MuseTalk／TensorRT 的完整模型
  執行組合與場域資料仍留到後續階段確認。

## 本次執行順序與通過條件

1. `uv lock --check`：確認 lock 與 pyproject 相容。
2. `uv sync --frozen --python 3.11 --group dev --group ci --extra vad`：在獨立
   `UV_PROJECT_ENVIRONMENT` 安裝 lock 固定版本，沿用 `pytorch-cu124` 來源。
3. `uv pip check`：檢查安裝套件 metadata 相容性。
4. `uv pip freeze`：保存實際版本。
5. GPU 探針：要求 CUDA build、`torch.cuda.is_available()` 為 true，建立 CUDA
   tensor 並執行矩陣乘法，核對結果與同步完成；沒有 GPU 不使用 fallback 或 skip。

每項精確 argv、工作目錄、環境覆寫、起迄時間與退出碼見 [commands.json](commands.json)。
鎖定安裝與後續命令日誌依其 `log` 欄位追查；失敗時保留原始退出碼與日誌。

## 實際結果

| 項目 | 結果 |
| --- | --- |
| Python | 3.11.16 |
| PyTorch | 2.5.0+cu124 |
| CUDA build／可用性 | 12.4／true |
| GPU | NVIDIA GeForce RTX 4090 |
| 真實 CUDA tensor 矩陣乘法 | 通過，核對結果與 GPU 同步完成 |
| pytest／Silero VAD | 9.1.1／6.2.1，使用 lock 固定版本 |
| 鎖檔檢查、frozen 安裝、相容性、版本清單、GPU 探針 | 五項命令退出碼皆為 0 |
| 原專案與快照的 lock／設定／workflow | 輸入 hash 維持不變 |

日誌：[安裝](locked-install.log)、[相容性](dependency-consistency.log)、
[實際版本](installed-packages.log)、[GPU 運算](gpu-compute-check.log)。
證據完整性見 [evidence-sha256.json](evidence-sha256.json)。

## 能證明與不能證明的事

若以上全部通過，代表這份 CUDA 測試環境能依 lock 建立，且 PyTorch 能在目前
GPU 真正執行運算。不代表 MuseTalk、TensorRT、STT／LLM／TTS、完整 WebRTC
影音或場域效能已通過；此輪沒有執行功能套件、靜態檢查或模型推理。

GPU 探針是依賴環境檢查，不列入先前 pytest／Node 案例數。JUnit 不適用。

## 對 CI 設計的影響與下一步

新 CI 執行 Python 驗證時需要實際 GPU runner。現有 `ubuntu-24.04` 與 CPU
安裝命令尚未變更；runner 放哪裡、何時觸發，仍須在設計階段確認。

補驗完成後等待使用者確認理解，再進入第 2 階段：在同一 CUDA 環境執行
Ruff、Pyright、ESLint，分別解說與保存結果。
