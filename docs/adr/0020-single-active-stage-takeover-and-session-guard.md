<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

---
status: accepted
---

# 單一活躍舞台、跨裝置接管與會話識別保護

在 NVIDIA Jetson AGX Orin 遠端服務部署中，單場即時對話的 GPU 負載已接近滿載且 MuseTalk 推論路徑不允許雙路並發；因此 `config/config_jetson.yaml` 將 `app.max_session` 收斂為 `1`，確保同一時間僅有一台裝置透過獨立**舞台**進行即時音視訊對話，而**控制台**預設停留在僅透過 HTTP 管理設定、規則與對話預設的狀態，不自動建立佔用 GPU 的 WebRTC 連線。

當已有活躍舞台且另一台裝置開啟 `/stage.html` 送出 `/offer`（未帶 `takeover: true`）時，後端回傳結構化的不可重試衝突回應（HTTP `409`、`code: "stage_occupied"`）而非過去的 `429`，讓新裝置停止背景自動重連並顯示「目前已有其他裝置正在使用舞台」與「接管此舞台」操作。使用者明確點擊接管後，新裝置以 `takeover: true` 重送 `/offer`，後端先透過資料通道送出 `session_displaced` 通知、再關閉遭取代的舞台會話與 WebRTC 連線；舊裝置收到 `session_displaced` 後立即釋放本地狀態並停止自動重連，呈現「舞台已由其他裝置接管」提示，避免雙端互相搶線。

所有與特定會話綁定的 HTTP 路由（`/human`、`/interrupt_talk`、`/isspeaking`、`/clear_history`、`/api/conversations/{sessionid}`、`/api/conversations/{sessionid}/clear` 與附件路由）統一透過 `src/server/session_guard.py` 核對 `client_id`（支援 `X-Client-Id` 標頭、`client_id` 查詢參數或 JSON 主體），並在已註冊會話缺少或錯配 `client_id` 時回傳 HTTP `403`。僅當**控制台**透過明確的角色標記（`X-Client-Role: console` 或 `client_role=console`）操作 `/api/conversations/{sessionid}` 或 `/clear` 控制指定**舞台**會話時，允許跨角色進行遠端管理與清空，同時仍禁止其冒用舞台身分發起 `/human` 或存取附件。

## Considered Options

- **維持 `max_session: 2` 或以 `429` 靜默重連**：會讓未關閉的舊分頁持續佔用或爭搶 Orin GPU 與 `llama-server` 資源，並導致新分頁陷入每秒一次的無止境重連迴圈。
- **直接關閉舊連線而不通知舊分頁**：舊舞台分頁會將關閉事件視為網路斷線並觸發 `scheduleStageReconnect()`，形成雙端交替搶線的迴圈。
- **僅在 `release_session` 檢查 `client_id`**：同網段其餘會話端點只要猜測或取得 6 位數 `sessionid` 即可插話、清空歷史或讀寫附件；未註冊 `client_id` 的離線單元測試情境仍維持相容，不強制要求測試腳手架偽造 `/offer` 狀態。
