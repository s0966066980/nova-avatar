<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 介面原型
Status: ready-for-human

依[規格](../spec.md)第 10 點。使用 ui-ux-pro-max 設計訓練工作台，做成可點擊的 HTML 原型（Artifact）與設計說明，放在 `.scratch/matcha-training/prototype/`：

- 流程：選語料來源（Edge 測試用老師／上傳錄音）→ 逐字稿（上傳／自動產生）→ 校對表（試聽、修改、排除、數字展開預覽）→ 訓練前檢查（舞台連線、顯存、使用限制標示）→ 訓練進度與日誌（可取消）→ 完成與試聽。
- Edge 確認畫面要顯示 MSA 條文，並清楚標示 Development only 與不提供匯出。
- 沿用控制台既有的視覺語彙，三份語系（zh-TW、zh-CN、en-US）的文字長度都要放得下。
- jetson 的 `TtsTrainingPanel.vue` 只當參考。

管理者確認原型後，才開始 08。

## Comments

- 2026-11-24：已完成可點擊原型與設計說明，放在 `.scratch/matcha-training/prototype/`：
  - [`index.html`](../prototype/index.html)：單一檔案、不連網，含十個畫面與可切換的情境（空、拒絕、錯誤、阻擋）、三種語系的介面文字、淺色與深色主題。
  - [`design.md`](../prototype/design.md)：流程、畫面清單、狀態、文案決定、無障礙，以及需要管理者確認的 12 項決定。
- 驗證：以無頭瀏覽器走完上傳與 Edge 兩條路徑，桌面與手機寬度（390 px）、淺色與深色、en-US 長文字都沒有橫向溢位或腳本錯誤；`scripts/check-integration.py` 通過。
- 狀態未更動；待管理者確認設計決定後才開始 08。
