<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 回歸與實機驗收
Status: resolved

依[完整規格](../spec.md)完成 integration audit、Python／web tests、build、雙角色真實 WebRTC soak 與可用觀看端檢查，分開回報已完成／未完成的 CWA 及瀏覽器實機驗收，記錄記憶體和首音延遲。

## Comments

2026-10-17：integration／rebranding audit 通過；Python 581 passed、3 skipped；web 100 passed，production build 通過，`git diff --check` 通過。原長測檔案中舞台完成 50 輪、控制台只有 42 輪，未將其視為雙端皆完成。已使用隔離設定重新啟動控制台 50 輪長測，結果寫入 `../role-soak-console-50.json`，資源量測寫入 `../role-soak-console-resources.json`。瀏覽器工具回報 `apps=[]`、`browsers=[]`，觀看端音畫驗收仍待可用瀏覽器。

2026-10-17 收尾：控制台已完成 50／50 輪，包含 100 次去／回程轉場，CWA 50 輪皆 available；連同原舞台 50 輪，兩端長測數量完成。新增 [單／雙素材預載量測](../role-preload-cost.json) 及 [A/V／快取量測補測](../role-timing-probe.json)。修正長測腳本的主角色首音欄位，改讀發話結束後的輪次指標，另存包含測試語音長度的輸入往返時間；既有長測檔案的舊欄位保留原值，不以它宣稱主角色首音成績。最終摘要見 [validation-results.json](../validation-results.json)。瀏覽器建立嘗試明確回報 `Browser is not available: iab`，本項僅剩觀看端交接語音／轉場／嘴型的實際音畫驗收，尚未標為完成。

最終補測：雙素材相較單素材增加約 1.24 GiB RAM／2 MiB 裝置 GPU 用量，預載約 3.37 s；中斷交接至接收 listening 事件約 2.17 ms，回答中返回至主角色 ready 約 1.73 s（包含返回轉場）。雙端補測的伺服器 A/V 配對偏移上限約 20.7 ms，這些事件／伺服器指標都不是觀看端實際播放延遲。量測腳本修改後再次完成完整回歸（581 passed／3 skipped、web 100 passed、build、integration audit）。所有本次啟動的 backend 與 owned llama-server 均正常關閉，未強制終止。

## Answer

使用者已指定 Playwright 控制本機 Chrome。已以有視窗的 Google Chrome 155.0.8059.84 完成控制台文字、舞台合成麥克風及雙端同時連線的實際瀏覽器驗收；用瀏覽器解碼音訊、畫面影格與截圖核對交接說明→轉場→專門回答的順序。取消、回答中返回、自訂靜音片與獨立回程特效、訪客閒置重置、原 tracks 保持、看板操作及手機直橫向均通過。

過程發現並修正兩個空狀態顯示問題與自訂影片預先露出首幀問題；修正後完整回歸為 Python **582 passed／3 skipped**、web **100 passed**、build、integration／rebranding audit 及 diff check 通過。證據與量測見 [chrome-acceptance.json](../chrome-acceptance.json)，截圖位於 `../chrome-artifacts/`。本次使用合成輸入，不聲稱檢查實體麥克風、喇叭或場域音響；先前 aiortc 50 輪紀錄保留原分類，沒有改稱為 Chrome 長測。測試上傳素材及本次啟動的服務已清理。
