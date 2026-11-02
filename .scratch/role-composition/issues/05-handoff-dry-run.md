<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 交接試算
Status: ready-for-agent
Blocked by: 02, 04

依[規格](../spec.md)「交接試算」。管理者選目前角色、輸入測試問題，後端以目前已儲存（或草稿，二擇一並說明）的組合呼叫路由，回傳目的成員、clarify 與原因；不播報、不寫入任何對話或記憶。新路由列 ADMIN；重的工作不在事件迴圈上（CODING_STANDARDS 規則 3）。

## Comments

### 2026-11-02 後端（rc/05-handoff-dry-run）

- **用已儲存的組合，不用草稿**：組合頁是各成員「各自儲存」，已儲存的內容就是套用後的行為；試算未儲存的草稿反而會讓試算結果與實際交接不一致。介面在試算區塊註明「以已儲存的組合試算（版本 N）」，有未儲存修改時提示先儲存。
- `POST /api/profiles/composition/dry-run`（ADMIN，已列入 `ROUTE_ACCESS`）：body `{current_profile_id, text}`（≤500 字）。回 `{code:0, revision, current_profile_id, target: id|null, target_name, handoff, clarification, reason, decided_by: "keyword"|"model", weather:{county,town,kind,start_date,end_date}}`。`target: null` ＝先釐清；`handoff` ＝目的角色不是目前角色。
- 以目前角色的設定檔組出模型設定，呼叫與對話相同的 `route_question`（共用 `RoutingClients`），歷史與已確認地點皆為空（等同新對話），整段在 `asyncio.to_thread`。不查天氣、不播報、不寫入對話、記憶或設定檔。
- 原因：`route_question(..., explain=True)` 只在試算時於 schema 最後加上 `reason`；grammar 先產生 `target`，所以原因不會改變選擇，對話的路由也不加這個欄位（不增加延遲）。關鍵字初篩與「天氣地點無法確認而改成先釐清」由伺服器給固定原因。
- 錯誤：未開啟角色交接或沒有生效成員 409；目前角色不是主數位人或生效成員 400；問題空白或過長 400；模型服務連不上 503。
- 測試 `tests/test_handoff_dry_run.py`。介面串接等 04 合併後接上。
