<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 套用視覺翻新到正式控制台
Status: ready-for-agent

依[規格](../spec.md)「視覺翻新」（Q13）。參考原型：[`prototype/settings-center-refresh.html`](../prototype/settings-center-refresh.html)（亦發布於 https://claude.ai/artifact/55tFqLiQww8ZD8cMT46sAy）。

- 把原型的設計語彙落到正式控制台（`web/`）：色彩 token（淺色與深色兩套，深色沿用舞台背景，品牌色為舞台說話藍）、字型（Plus Jakarta Sans、Noto Sans TC、數字與 ID 用等寬字）、4px 間距與 6/10/14 圓角、狀態四層（橫幅、欄位錯誤、狀態膠囊、通知）皆附圖示不只靠顏色、左側系統狀態清單。
- 色彩以 CSS 變數集中定義；「系統偏好與自訂」的主題選項（跟隨系統／淺色／深色）實際生效。
- 範圍：整個控制台（即時演播控制台與系統設定中心）；數位人舞台頁不變。
- 不改任何設定行為；保留 04 的版面與版面回歸測試（必須仍通過），必要時更新截圖斷言。
- 附 1920×1080、1280×720 深淺兩套截圖於 Comments（截圖放 scratchpad）。

## Comments
