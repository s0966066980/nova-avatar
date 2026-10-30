<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 套用視覺翻新到正式控制台
Status: resolved

依[規格](../spec.md)「視覺翻新」（Q13）。參考原型：[`prototype/settings-center-refresh.html`](../prototype/settings-center-refresh.html)（亦發布於 https://claude.ai/artifact/55tFqLiQww8ZD8cMT46sAy）。

- 把原型的設計語彙落到正式控制台（`web/`）：色彩 token（淺色與深色兩套，深色沿用舞台背景，品牌色為舞台說話藍）、字型（Plus Jakarta Sans、Noto Sans TC、數字與 ID 用等寬字）、4px 間距與 6/10/14 圓角、狀態四層（橫幅、欄位錯誤、狀態膠囊、通知）皆附圖示不只靠顏色、左側系統狀態清單。
- 色彩以 CSS 變數集中定義；「系統偏好與自訂」的主題選項（跟隨系統／淺色／深色）實際生效。
- 範圍：整個控制台（即時演播控制台與系統設定中心）；數位人舞台頁不變。
- 不改任何設定行為；保留 04 的版面與版面回歸測試（必須仍通過），必要時更新截圖斷言。
- 附 1920×1080、1280×720 深淺兩套截圖於 Comments（截圖放 scratchpad）。

## Comments

### 2026-10-30 實作結果

- 規劃（`ui-ux-pro-max`）：沿用既有元件與 class，只把原型語彙對應上去，不重寫結構；所有 id、v-model 與事件繫結不變。
- 色彩 token：`web/src/console-prototype.css` 以 `light-dark(淺, 深)` 一處定義淺深兩套（深色用舞台背景 `#08090c`、品牌色舞台說話藍 `#7c9cff`）；舊變數名（`--text-primary`、`--brand-light` 等）改為指向新 token。移除 `App.vue` 以 JS 逐一寫入行內色彩的做法。舞台畫面（控制台 9:16 預覽、設定中心舞台預覽）固定 `color-scheme: dark`，維持舞台配色；`stage.html` 未改。
- 主題：新增 `web/src/consoleTheme.js`。「系統偏好與自訂」改為跟隨系統／淺色／深色三選項（附色票），點選即生效並存於 `nova-avatar-theme`；跟隨系統時移除 `data-theme`，作業系統切換深淺色即時跟著變。舊的 obsidian/bento 設定自動對應。`main.js` 在掛載前套用，登入頁也跟著主題。
- 字型：Plus Jakarta Sans、JetBrains Mono 改由 npm（`@fontsource/*@5.3.0`，OFL-1.1，僅 latin 子集）打包，斷網可用；中文用 Noto Sans TC，未安裝時退回系統的 Noto Sans CJK TC（本機已有）。數字、ID、session 編號用等寬字。
- 間距與圓角：4px 間距 token（`--s1`…`--s8`），元件圓角統一為 6/10/14。
- 狀態四層：橫幅 `.status-banner`（GPU 警示、設定讀取、待套用）、欄位與區塊錯誤（以 CSS 在既有錯誤訊息前加圖示，錯誤／警示圖示不同）、狀態膠囊（WebRTC 連線、RAGFlow 已連線）、通知（左側語氣色條＋圖示，`aria-live`）。WebRTC 未連線時圓點改灰色（原本恆為綠色）。表情符號圖示改為 bootstrap-icons。
- 左側系統狀態清單（`web/src/systemStatus.js`）：控制台連線、舞台場次、後端服務、本機 LLM（未全載入 GPU 時警示）、語音辨識、待套用設定；每列圖示＋名稱＋說明。高度 ≤ 820px 時改單行，1280×720 導覽與狀態都不必捲動。
- 無障礙：全域 `:focus-visible` 品牌色 2px 焦點框（移除原本拿掉焦點框的規則、開關改在軌道上畫焦點框）；設定分頁以方向鍵切換時焦點跟著移動；`prefers-reduced-motion` 關閉動畫與轉場；主要按鈕文字改用 `--on-brand`，深色主題不再出現白字配淺藍底。
- 測試：`console-theme.test.js`、`system-status.test.js`、`console-theme-tokens.test.js`（token 對比，淺深兩套每組文字／表面 ≥ 4.5:1）、`console-visual.test.js`（Chrome 實際渲染控制台、9 種設定頁狀態與登入頁，淺深 × 1920×1080／1280×720，逐一合成背景計算可見文字對比；主題三選項切換、重新整理後保留；焦點框；減少動態）。04 的 `settings-layout.test.js` 改用共用 `tests/helpers/browserHarness.js`，仍通過。
- 截圖（不進 git）：`/tmp/claude-1000/-home-oliver-nova-avatar/f284899e-3e7d-40e8-bf07-77d0ecc09394/scratchpad/cvs07-shots/`，`console-*`、`settings-<分頁>-*` 各含 1920x1080／1280x720 × light／dark，`login-*` 為 1280x720 淺深兩張（共 42 張）；`layout/` 為 04 版面測試截圖。重產：於 `web/` 執行 `CONSOLE_VISUAL_SCREENSHOTS=<目錄> node --test tests/console-visual.test.js`。
- 驗證：`npm run lint`、`npm test`（241 通過）、`npm run build`、ruff、pyright、`check-integration.py` 皆通過；pytest 1384 通過（兩個已知基線測試排除）。
