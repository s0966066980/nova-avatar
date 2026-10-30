<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 系統設定中心版面（16:9）
Status: resolved
Blocked by: 02

依[規格](../spec.md)「版面」。先以 `ui-ux-pro-max` 技能檢視現況與提出版面，再實作；保留現有視覺風格與所有設定行為。

- 修正：`100vw` 橫向捲動、雙欄缺 `minmax(0,1fr)`、卡片 `min-width`、9:16 預覽最小高度、固定寬度與行內樣式（清單見 console-ui-map.md）。
- 1920×1080 主要設定一屏可見；1280×720 不跑版；區塊內捲動。
- 加入能防止回歸的檢查（例如在 1920×1080、1280×720 下以無頭瀏覽器渲染各分頁，斷言沒有橫向捲動、區塊不重疊），並納入 CI 或 npm test。
- 附各分頁在兩種尺寸的截圖於 Comments（截圖放 scratchpad，不進 git）。

## Comments

### 2026-10-30 實作結果

- 版面規劃（`ui-ux-pro-max` 檢視）：16:9 下改為「分頁填滿可視高度、每個區塊在自己的格子內捲動」；窄於 1280 或矮於 640 時退回單欄整頁捲動。配色、字型、元件樣式不變；所有 id、v-model 與事件繫結逐一比對未變。
  - 對話記憶與語系：左欄記憶與 Context、右欄保留上限與聲音（預設展開）。
  - 數位人、AI 與知識設定：設定檔清單與編輯器各自捲動，分區按鈕列固定在編輯器頂端；交接頁改兩欄（組合＋轉場｜交接規則）。
  - 閒置招呼：左欄開關、時間與狀態，右欄招呼內容；拿掉 `max-width:1100px`。
  - 訪客互動與語音辨識：三欄（清場｜VAD｜語音辨識）。
  - 數位人與畫質：兩欄（1 : 1.25），角色縮圖改自動欄數。
  - 舞台與看板排版：≥1600 寬為「背景＋看板樣式｜舞台元素位置（新卡片：字幕帶、九宮格、麥克風、展開按鈕、輸入框）｜9:16 預覽」；1280–1599 為「設定欄整欄捲動｜預覽」。9:16 預覽改以容器尺寸取最大可容納大小，移除 760px 最小高度。
  - 系統偏好與自訂：兩欄。
- 修正：`100vw` 改 `100%`、導覽軌 `clamp(240px,16vw,260px)`、主區移除 `calc(100vw-260px)`；網格一律 `minmax(0,1fr)`；卡片 `min-width:0` 並以容器查詢在窄卡片把標籤疊到控制項上方；卡片標題列可換行、捲動時固定；1280 斷點改為 <1280；SettingsPanel 內除舞台預覽定位外的行內樣式全改為 class；角色縮圖改絕對定位，直式預覽不再撐破 4:3 框；設定區改用主題邊框色細捲軸。
- 回歸檢查：新增 `web/tests/settings-layout.test.js`（納入 `npm test`）。以 Vite 開發伺服器（不設 proxy）加 Playwright（`playwright-core@1.64.1` devDependency，使用系統 Chrome 或 `CHROME_PATH`，保留傳統捲軸）渲染 9 種狀態 × 1920×1080、1280×720，API 全由 `web/tests/fixtures/settingsApi.js` 假資料回應。斷言：頁面不橫向捲動、版面框不超出視窗、設定頁本身不縱向捲動、區塊不重疊不超出、內容不凸出區塊、區塊內容超出時必須可捲動、無頁面錯誤。無 Chrome 時略過，CI（`CI` 環境變數）則失敗；GitHub ubuntu-24.04 runner 內建 Chrome。
- 順手修正：`AvatarProfiles.vue` 監看共用設定檔庫時對 reactive proxy 呼叫 `structuredClone` 會丟錯（切到閒置招呼後即觸發），改傳 `toRaw`。
- 發現未修（行為問題，非本單範圍）：VAD「最小靜音判定時間」滑桿綁 `vadDraft.min_silence_duration_ms`，但狀態與送出欄位是 `min_silence_ms`，滑桿無作用、數值顯示空白。
- 截圖（不進 git）：`/tmp/claude-1000/-home-oliver-nova-avatar/f284899e-3e7d-40e8-bf07-77d0ecc09394/scratchpad/cvs04-shots/<分頁>-<寬>x<高>.png`，共 18 張；修改前在同目錄 `before/`。重產：`SETTINGS_LAYOUT_SCREENSHOTS=<目錄> node --test tests/settings-layout.test.js`（於 `web/`）。
- 驗證：`npm run lint`、`npm test`（218 通過）、`npm run build`、ruff、pyright、`check-integration.py` 皆通過；pytest 1334 通過，僅兩個已知基線失敗。
