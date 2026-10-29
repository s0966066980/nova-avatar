<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 路由、檢索與主回答並行
Status: ready-for-agent
Blocked by: 01

依[規格](../spec.md)與 [ADR 0022](../../../docs/adr/0022-run-routing-retrieval-and-answer-concurrently.md)。目前 `src/server/voice_session.py:843-952` 依序執行路由（`src/profiles/routing.py:60`，非串流、max_tokens 384）、RAGFlow 檢索，再開始主回答。

- 路由與檢索同時開始；主回答在檢索完成或 400 ms 上限時開始，不等路由。
- 路由判定前，可播片段可合成但不送出音訊；判定不交接即放行，判定交接即以輪次隔離取消並走交接。
- 檢索逾時：本輪不帶檢索，控制台顯示「本輪未取得檢索」。
- 測試：一般輪次首音不含路由時間；交接輪次不播出任何主回答音訊；檢索逾時行為；取消後無殘留片段。

## Comments
