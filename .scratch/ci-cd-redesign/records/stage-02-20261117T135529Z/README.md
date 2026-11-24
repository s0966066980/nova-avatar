<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 第 2 階段：靜態檢查

執行狀態：passed
理解確認：pending
日期：2026-11-17；每項命令時間以 UTC 保存

## 目的

在執行功能情境前，先找出設定中可機械檢查的程式問題。這些工具讀取程式，
沒有執行對話或模型推理；在 CUDA 環境執行不表示它們使用 GPU 推理。

## 來源與環境

- 來源 commit：`b1afdce7429eb166d3d36f6e233a07a14fbc2d52`，沿用第 1 階段乾淨來源快照。
- 沿用使用者已確認的獨立 CUDA 環境，不重新安裝或解析依賴。
- Python 3.11.16、PyTorch 2.5.0+cu124、CUDA 12.4 且可用。
- Ruff 0.17.1、Pyright 1.1.414；前端使用 Node.js 22.23.5。
- 執行前確認來源 HEAD、已追蹤差異與設定檔 hash；執行後輸入 hash 不變。
- 原始工作目錄狀態：[working-tree-status-before.txt](working-tree-status-before.txt)。
- 來源、環境覆寫、輸入 hash 與時間：[manifest.json](manifest.json)。
- 環境確認：[environment-check.log](environment-check.log)、[Node 版本](node-version.log)。

## 三項檢查與結果

| 工具／命令 | 實際範圍 | 主要能找到什麼 | 結果 |
| --- | --- | --- | --- |
| `uv run --no-sync ruff check .` | 依設定選取的 255 個 Python 檔，來自 src、scripts、tests；排除部分繼承引擎 | 已啟用的語法／名稱錯誤、部分安全與 async 阻塞規則 | 退出碼 0；All checks passed |
| `uv run --no-sync pyright` | 只分析 src/server，以設定中的 Python 3.10 為分析目標 | 已啟用的型別／控制流檢查，例如可能尚未賦值的變數 | 退出碼 0；0 errors、0 warnings |
| `npm run lint` | web/src、tests、stage.html、vite.config.js、eslint.config.js | JavaScript／Vue correctness 規則與未經例外審查的 v-html；涵蓋舞台 inline script | 退出碼 0；max-warnings 0 |

Ruff／Pyright 的工作目錄是來源快照 root；ESLint 是來源快照 `web/`。
三項彼此獨立，這次並行執行，各自保存起迄時間和退出碼。

原始日誌：[Ruff](ruff.log)、[Pyright](pyright.log)、[ESLint](eslint.log)。
精確命令：[Ruff](ruff-command.json)、[Pyright](pyright-command.json)、
[ESLint](eslint-command.json)。Ruff 實際選檔清單：[ruff-files.log](ruff-files.log)。

## 範圍限制

- Ruff 不是檢查所有 Python 規則；安全與 async 也僅是設定中啟用的規則。
  ernerf、talkinggaussian、ultralight、wav2lip、MuseTalk utils／whisper 等目錄被排除。
- Pyright 不是全專案完整型別驗證。它只涵蓋 src/server，並關閉部分既有型別債務
  規則；安裝 Python 3.11 不會自動改變設定中的 3.10 分析目標。
- ESLint 關閉部分未使用程式規則，並排除 dist、node_modules、srs.sdk.js。
  v-html 的既有審查例外仍依程式中的 disable 註解處理。
- 三項通過只證明已啟用的規則未回報問題，不證明辨識正確、語音可用、GPU 模型
  正確、影音同步或場域延遲達標，也不是完整安全稽核。
- 沒有執行 pytest、Node 功能測試或正式建置。案例數與 JUnit 不適用；本階段
  以各工具退出碼與診斷訊息判斷，不把「3 項檢查」加進先前測試案例總數。

## 通過條件與證據

三項命令均需退出碼 0；ESLint 依既有命令要求 0 warnings。結果全部符合，
沒有失敗、修正或重跑，也沒有自動修正程式。

證據完整性清單：[evidence-sha256.json](evidence-sha256.json)。
第 1 階段使用者回覆 `ok` 的確認記錄已補入設計地圖。

## 下一步

等待使用者確認理解本階段，再進第 3 階段：品牌／授權與離線整合稽核，
以及 governance 的 19 個已盤點案例，分別保存命令、逐項結果與跳過理由。
