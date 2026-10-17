<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 控制台設定與舞台返回
Status: resolved

依[完整規格](../spec.md)完成設定檔、角色組合、定向轉場、天氣地點、輸入模式與返回控制。兩端角色狀態同步、對話按角色區分；以 meaningful web tests 與 build 驗證。

## Comments

2026-10-16：已接上角色設定頁、去回程媒體編輯、訪客／控制台測試模式、角色對話標籤與兩端返回。轉場清字幕及看板，保留麥克風授權。前端 100 項測試及 build 已通過；沒有可用瀏覽器，觀看端視覺驗收尚未執行。

2026-10-17：100 項前端測試及 production build 再次通過，實作與自動驗證完成；瀏覽器工具仍回報空清單，觀看端音畫驗收保留於 [05](05-validation.md)，本項完成不代表已完成該人工檢查。

2026-10-17 Chrome 驗收：修正控制台空字幕退回固定示例回答，以及舞台看板按鈕的 CSS 覆蓋 `hidden` 屬性兩個實際畫面問題。[Chrome 回歸腳本](../chrome_caption_regression.py) 已分別重現失敗並於修正後通過；真實看板的關閉／展開、返回後清空畫面、375×812／812×375 舞台及 reduced-motion 檢查亦通過。100 項前端測試及 build 保持通過。
