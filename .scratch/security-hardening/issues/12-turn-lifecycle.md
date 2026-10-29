<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 回合生命週期收尾
Status: ready-for-agent
Blocked by: 11

依[規格](../spec.md)。

- 回覆非空但沒有任何可唸片段（全被清除或純看板）時回合永不結束（`src/server/voice_session.py:887-918,1016-1037`；`src/avatars/base.py:163-165`）。結束時片段數為 0 即立即提交並結束。
- 串流熔斷器開啟後不會關閉：正式程式從不呼叫 `record_streaming_health_probe`（`src/server/reply_streaming/circuit_breaker.py`；`voice_session.py:1627`）；問候強制串流（`:1674`）失敗也計入。加入冷卻後半開或成功探測；問候失敗不計入。
- `_consume_track`（`:464-470`）非取消例外後連線仍在，aiortc 接收佇列無上限（約 0.7 GB/h）。例外時關閉 peer connection 讓前端重連。
- 未追蹤的 task（`:309,321,343,349,354`）收進集合並於 `close()` 取消；`_finalize_task` 覆寫問題一併修正。
- 每回合增長的集合（`:160-161`；`base.py:155,322-325`）改為有上限。

完成：每項的回歸測試；完整 CI 通過。

## Comments
