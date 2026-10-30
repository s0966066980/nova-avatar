<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 系統設定中心版面（16:9）
Status: ready-for-agent
Blocked by: 02

依[規格](../spec.md)「版面」。先以 `ui-ux-pro-max` 技能檢視現況與提出版面，再實作；保留現有視覺風格與所有設定行為。

- 修正：`100vw` 橫向捲動、雙欄缺 `minmax(0,1fr)`、卡片 `min-width`、9:16 預覽最小高度、固定寬度與行內樣式（清單見 console-ui-map.md）。
- 1920×1080 主要設定一屏可見；1280×720 不跑版；區塊內捲動。
- 加入能防止回歸的檢查（例如在 1920×1080、1280×720 下以無頭瀏覽器渲染各分頁，斷言沒有橫向捲動、區塊不重疊），並納入 CI 或 npm test。
- 附各分頁在兩種尺寸的截圖於 Comments（截圖放 scratchpad，不進 git）。

## Comments
