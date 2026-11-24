<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# CPU 檢查與 CUDA 驗收的用途

記錄日期：2026-11-17
狀態：歷史背景；使用者已指定本版 CUDA-only，以下兩層建議已被取代。

本版不建立 CPU-only CI 路線；後續 Python 驗證統一使用有 GPU 的 CUDA 環境。
先前 CPU 安裝結果僅保留為歷史證據，不作為本版發布驗收。

## 為什麼第 1 階段安裝 CPU PyTorch

第 1 階段重現的是目前 repository 的離線 CI 安裝方式，不是在決定場域改用 CPU。
[ci.yml](../../.github/workflows/ci.yml) 使用標準 `ubuntu-24.04` runner，安裝命令
明確指定 `--no-sources --torch-backend cpu`。因此隔離環境取得 CPU build。

標準 GitHub-hosted Linux runner 沒有配置 NVIDIA GPU；需要 GPU 的 runner 是
另外的配置選擇。參考 [GitHub runner 官方說明](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。
這是目前選用 CPU 安裝的實際設定與環境背景，不代表 CPU 能涵蓋 CUDA 驗收。

## 原專案環境仍使用 CUDA

[pyproject.toml](../../pyproject.toml) 將 PyTorch 套件來源設為 `pytorch-cu124`。
本次唯讀檢查原專案 `.venv`，得到：

```json
{"torch":"2.5.0+cu124","cuda_build":"12.4","cuda_available":true}
```

檢查沒有安裝或變更套件。第 1 階段的 CPU 環境位於獨立 cache 目錄，未取代它。
`torch.cuda.is_available()` 表示 CUDA 目前可用，不代表已跑過模型或完成場域驗收。
函式定義見 [PyTorch 官方說明](https://docs.pytorch.org/docs/main/generated/torch.cuda.is_available.html)。

## 建議的新 CI/CD 分工

| 層級 | 環境 | 要保護的事項 | 不能取代的驗證 |
| --- | --- | --- | --- |
| 通用回歸檢查 | CPU，適合一般 GitHub runner | 靜態檢查、路由權限、對話規則、解析、錯誤與取消處理等不依賴 GPU 的測試 | 真實 GPU 推理、CUDA／TensorRT 相容性與影音效能 |
| 場域發布驗收 | 實際 GPU 主機與 CUDA PyTorch | 選定模型載入、實際 GPU 推理、WebRTC 影音與延遲等共同確認的場域案例 | 通用回歸測試；兩層各自保留結果 |

建議場域發布必須有 CUDA 實測證據，不能僅以 CPU 測試通過判定可發布。
僅安裝 CUDA wheel，或只檢查 `cuda_available=true`，也不足以當作 GPU 驗收。
哪些 GPU 情境必須阻擋發布、使用哪台 runner、何時執行，仍需逐階段確認。

## 對版本鎖定的影響

目前待決問題應稱為「CPU 回歸環境與 CUDA 執行／驗收環境的依賴固定方式」，
不能只固定 CPU 套件就宣告場域環境可重現。兩種環境應各自記錄實際版本與證據；
採單一 lock 的不同來源設定、或分開的鎖定方案，尚未決定。
