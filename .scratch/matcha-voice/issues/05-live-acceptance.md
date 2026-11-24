<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 實機驗收
Status: ready-for-human
Blocked by: 02, 03, 04

依[規格](../spec.md)「驗收」。在已載入 MuseTalk 和 LLM 的實機上，把一個數位人設定檔改用 hsiaochen-edge：

- 舞台實際對話時有聲音，嘴型同步。中文和英文各測一次。
- 首音 P95 ≤ 0.7 s，以應用日誌的 `first audio:` 為準。
- 連續 50 輪對話沒有失敗。
- `.github/workflows/ci.yml` 的每個步驟，以及現版主要基準，全部通過。

結果和使用者的試聽意見寫在 Comments。
