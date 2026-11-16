<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

---
status: accepted
---

# `:8010` 單一入口、單一活躍舞台、跨裝置接管與會話識別保護

在 NVIDIA Jetson AGX Orin 遠端服務部署中，正式執行模式不再啟動前景 Vite 開發伺服器（`:3000`），改由 `scripts/start-server.sh` 搭配 `src/server/app.py` 在 `:8010` 單一入口直接提供已建置的 `web/dist` 靜態頁面、HTTP API 與 WebRTC（並於遠端存取時停用僅限本機的 `127.0.0.1:8088` 直連按鈕與 `tkinter` 選檔視窗）。同時因單場即時對話的 GPU 負載已接近滿載且 MuseTalk 推論路徑不允許雙路並發，`config/config_jetson.yaml` 將 `app.max_session` 收斂為 `1`，確保同一時間僅有一台裝置透過獨立**舞台**進行即時音視訊對話，而**控制台**預設停留在僅透過 HTTP 管理設定、規則與對話預設的狀態，不自動建立佔用 GPU 的 WebRTC 連線。

當已有活躍舞台且另一台裝置開啟 `/stage.html` 送出 `/offer`（未帶 `takeover: true`）時，後端回傳結構化的不可重試衝突回應（HTTP `409`、`code: "stage_occupied"`）而非過去的 `429`，讓新裝置停止背景自動重連並顯示「目前已有其他裝置正在使用舞台」與「接管此舞台」操作。使用者明確點擊接管後，新裝置以 `takeover: true` 重送 `/offer`，後端先透過資料通道送出 `session_displaced` 通知、再關閉遭取代的舞台會話與 WebRTC 連線；舊裝置收到 `session_displaced` 後立即釋放本地狀態並停止自動重連，呈現「舞台已由其他裝置接管」提示，避免雙端互相搶線。

所有與特定會話綁定的 HTTP 路由（`/human`、`/interrupt_talk`、`/is_speaking`、`/clear_history`、`/humanaudio`、`/set_audiotype`、`/record`、`/api/sessions/release`、`/api/conversations/{sessionid}`、`/api/conversations/{sessionid}/clear` 與 `/api/conversations/{sessionid}/attachments` / `interaction` 附件路由）統一透過 `src/server/session_guard.py` 搭配 `ServerState` 查詢擁有者與角色，核對 `client_id`（支援 `X-Client-Id` 標頭、`client_id` 查詢參數或 JSON／表單主體），並在已註冊會話缺少或錯配 `client_id` 時回傳 HTTP `403`（`/api/sessions/release` 一律要求已註冊且相符之 `client_id`）。僅當**控制台**透過明確的角色標記（`X-Client-Role: console` 或 `client_role=console`）操作 `/api/conversations/{sessionid}` 或 `/api/conversations/{sessionid}/clear` 控制指定**舞台**會話時，允許跨角色進行遠端管理與清空：若系統中存在活躍的控制台 WebRTC 會話，呼叫端仍須提供與活躍控制台相符的 `client_id`；若控制台處於不建置 WebRTC 的純 HTTP 管理模式，僅允許本機 loopback 來源（或與目標舞台相同之 `client_id`），拒絕遠端未註冊來源冒充控制台，同時仍禁止其冒用舞台身分發起 `/human`、`/record` 或存取附件。

## Considered Options

- **維持雙埠 `:3000` + `:8010` 並保留 `max_session: 2` 與 `429` 靜默重連**：Vite dev proxy 在遠端長期常駐增加額外程序與憑證同步成本，而未關閉的舊分頁會持續佔用或爭搶 Orin GPU 與 `llama-server` 資源，並導致新分頁陷入每秒一次的無止境重連迴圈。
- **直接關閉舊連線而不通知舊分頁**：舊舞台分頁會將關閉事件視為網路斷線並觸發 `scheduleStageReconnect()`，形成雙端交替搶線的迴圈。
- **僅在 `/api/sessions/release` 檢查 `client_id` 或無條件信任 `X-Client-Role: console`**：同網段其餘會話端點只要猜測或取得 6 位數 `sessionid` 即可插話、錄製、清空歷史或讀寫附件，甚至偽造 `X-Client-Role: console` 遠端重置舞台會話；未註冊 `client_id` 的離線單元測試情境仍維持相容，不強制要求測試腳手架偽造 `/offer` 狀態。
