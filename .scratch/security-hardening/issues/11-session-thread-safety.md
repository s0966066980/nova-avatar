<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 語音工作階段執行緒安全
Status: resolved

依[規格](../spec.md)。皆在 `src/server/voice_session.py`。

- 問候失敗：`_event_loop` 只在 `start_read_aloud_turn`（`:612`）與 `_generate_turn`（`:768`）設定。第一輪前的閒置招呼 TTS 失敗時，`on_fragment_synthesis_failed`（`:1119-1127`）在 TTS 執行緒直接處理 → aiortc 拋 RuntimeError → `_send_event`（`:1957-1966`）永久把 `_event_sink` 設 None，kiosk 失聰到重新整理。改為在 `prepare()`（`:223`）就記錄 loop；loop 不存在時只記錄並丟棄。`_send_event` 不因非 loop 執行緒的錯誤永久關閉通道。
- 打斷競態：`interrupt()` 在 `await asyncio.sleep(0.3)` 後無條件 `_turn_id = None`（`:1335`）；只有 `start_text_turn` 持 `_text_turn_lock`，其他打斷來源（data channel `:354`、role_stop `:318`、`/clear_history`、`/api/conversations/{id}/clear`、apply_conversation `:414`）不持鎖。改為記錄進入時的 generation，sleep 後只在未變時清除；所有打斷來源共用同一把鎖。

完成：從非 loop 執行緒觸發失敗後事件通道仍可用、兩個重疊打斷後能開始新回合的回歸測試；完整 CI 通過。

## Comments

### 2026-10-29

- `prepare()` 一開始即記錄會話 event loop；`on_fragment_synthesis_failed` 在 loop 不存在或已停止時只記錄警告並丟棄，不再於 TTS 執行緒直接處理。
- `_send_event` 若不在會話 loop（工作執行緒或 Edge 私有 loop）上，改以 `call_soon_threadsafe` 轉送；非會話 loop 上的送出錯誤只記錄丟棄，不再永久關閉事件通道。
- `_text_turn_lock` 更名為 `_turn_lock`；`interrupt()` 自行持鎖，已持鎖的呼叫端（`start_text_turn`、`cancel_text_request`、`start_read_aloud_turn`）改呼叫 `_interrupt_locked()`，所有打斷來源與回合受理共用同一把鎖。
- 打斷記錄進入時的 generation，tail guard 後僅在未變時清除 `_turn_id` 並重開收音；已變則只補送被打斷回合的指標。
- 回歸測試：`tests/test_voice_session.py::SessionThreadSafetyTests`（5 項）。`tests/test_conversation_attachments.py` 的重疊打斷測試改為攔截 `_interrupt_locked`，意圖不變。
- 驗證：ruff、check-integration、前端 lint/test/build 通過；pytest 803 通過、2 失敗皆因 worktree 缺少 `models/`（MuseTalk 權重、本機 OCR），與本變更無關。
