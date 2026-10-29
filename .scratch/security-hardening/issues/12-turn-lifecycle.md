<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 回合生命週期收尾
Status: resolved
Blocked by: 11

依[規格](../spec.md)。

- 回覆非空但沒有任何可唸片段（全被清除或純看板）時回合永不結束（`src/server/voice_session.py:887-918,1016-1037`；`src/avatars/base.py:163-165`）。結束時片段數為 0 即立即提交並結束。
- 串流熔斷器開啟後不會關閉：正式程式從不呼叫 `record_streaming_health_probe`（`src/server/reply_streaming/circuit_breaker.py`；`voice_session.py:1627`）；問候強制串流（`:1674`）失敗也計入。加入冷卻後半開或成功探測；問候失敗不計入。
- `_consume_track`（`:464-470`）非取消例外後連線仍在，aiortc 接收佇列無上限（約 0.7 GB/h）。例外時關閉 peer connection 讓前端重連。
- 未追蹤的 task（`:309,321,343,349,354`）收進集合並於 `close()` 取消；`_finalize_task` 覆寫問題一併修正。
- 每回合增長的集合（`:160-161`；`base.py:155,322-325`）改為有上限。

完成：每項的回歸測試；完整 CI 通過。

## Comments

### 2026-10-29 實作結果

- 無可唸片段：`_generate_turn`、`_speak_fixed`（非問候）與朗讀在送出後檢查片段數，為 0 即以 `no_audio` 提交並結束回合、重開收音。
- 熔斷器：`ReplyCircuitBreaker` 加入 60 秒冷卻；冷卻後半開以串流重試，成功即關閉、失敗重新冷卻；legacy 回合成功不會關閉。問候的成敗都不計入（`_counts_toward_circuit`）。
- 麥克風軌：`start_track(track, on_lost=...)`；非取消例外時 `/offer` 排程 `cleanup()` 關閉 peer connection，前端據此重連。
- 背景 task：控制訊息啟動的 task 改用 `_spawn` 收進 `_background_tasks`，`close()` 一併取消；finalize 執行中不再接受第二次 finalize，且 `finally` 只清除自己的參照。
- 有上限的集合：回合去重集合改為 `RecentKeys`（64；看板回執 256）；`BaseAvatar._media_sequences` 最多保留 8 個回合。
- 測試：新增 `tests/test_turn_lifecycle.py`（13 項）與 `test_webrtc_lifecycle.py` 一項；完整 CI 通過（pytest 847 passed，僅兩項已知的 worktree 基線失敗）。
