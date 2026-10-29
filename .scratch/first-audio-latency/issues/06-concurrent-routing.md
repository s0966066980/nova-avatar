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

### 2026-10-30 實作（分支 `fal/06-concurrent-routing`）

- 並行（`src/server/voice_session.py` `_route_concurrently`）：角色啟用且非交接續答輪次時，路由（`before_generate`）與「附件＋檢索」同時開始；主回答在檢索完成或 400 ms（`RETRIEVAL_BUDGET_SECONDS`）後以「目前角色自答」計畫開始，不等路由。交接續答輪次本來就不呼叫路由 LLM，維持依序。
- 計畫比對（`src/profiles/coordinator.py`）：`speculative_plan()` 是路由判定「留在目前角色、不加事實」時 `before_generate` 會回傳的計畫（主角色為 `{"context": ANSWER_CONTEXT}`）；`continues()` 判斷交接續答。路由結果與它相同即放行；固定回覆（交接說明、澄清、錯誤）改播固定回覆；同角色但帶天氣或路由背景時，丟棄後以路由計畫重新產生主回答（沿用已完成的附件與檢索）。
- 放行前不送音訊：TTS 執行緒在 `accepts_media(..., "avatar_audio_enqueue")` 等待路由判定（可合成、不送出）；主回答的用戶端事件（`assistant_response_*`、看板、`rag_retrieval`）暫存，放行後依序送出，丟棄時捨棄。保留期間不觸發播放停滯判定。未改 `src/avatars/`。
- 輪次隔離取消：同一 turn_id、generation +1、新 `TurnContext`、`flush_talk`、清除片段；等被隔離的 LLM 工作執行緒結束後丟棄其待提交歷史（`discard_pending_history`），再開始固定回覆或重新產生，避免同一輪歷史衝突。隔離後的錯誤以新 generation 回報。工作執行緒送回的增量文字、看板、模式事件於 loop 端再驗 generation。
- 檢索逾時：`rag_retrieval` 狀態 `timeout`，本輪不帶檢索；控制台顯示「本輪未取得檢索：知識庫回應逾時，本輪沿用一般回答。」（`web/src/App.vue`）。
- 指標：`pre_answer` 不再含路由，只到實際播出的主回答開始（或固定回覆送出）；`routing` 為並行的路由時間；新增 `routing_hold`＝已合成音訊等待路由判定的時間（屬 `avatar_to_webrtc_commit`，路由先完成時為 0）。丟棄的主回答以 `discard_answer_stages()` 清掉 `model_info` 之後各階段並重開 `pre_answer`，交接輪次量到的是交接說明。`latency_baseline.py` 的依序鏈說明同步更新，對齊公式不變。
- 測試：新增 `tests/test_concurrent_routing.py` 17 項（主回答不等路由、保留期間不送音訊與事件、首音不含路由時間與 `routing_hold`、交接輪次不播主回答且無殘留片段、歷史丟棄順序、重新產生、續答依序、取消計畫、隔離後錯誤、檢索逾時與預算內使用、檢索來源隨交接丟棄、真實 coordinator 契約、中斷）。舊測試中「交接輪次 LLM 不得被呼叫」改為「被丟棄的主回答不得播出」（ADR 0022 取捨），ticket 01 的階段測試改為並行語意。
- 驗證：ruff、pyright、`scripts/check-integration.py` 通過；pytest 全套僅已知 2 項 worktree 基準失敗；web `npm run lint`、`npm test`（209）、`npm run build` 通過。合併 `first-audio-latency`（04、07、09、13）後重跑：pytest 1213 passed（僅已知 2 項失敗）、web 210 passed，其餘同上；13 的 `wait_for_audio` 在保留放行後才收到音訊，互不影響。

### 待實機驗證

依實作指南不得重啟共用後端或建立舞台 WebRTC 工作階段，`Status` 維持 `ready-for-agent`。步驟（合併 01 與本票後的程式碼）：

1. 以新程式碼重啟後端，確認 llama-server 仍為 4 slots（`grep -- "-np\|n_slots\|slots" logs/llama-server.log | tail -3`），否則路由與主回答會在伺服器端排隊。
2. 關閉 kiosk 舞台頁後執行：
   ```
   cd /home/oliver/nova-avatar
   .venv/bin/python scripts/measure_first_audio.py --rounds 1 --warmup 1 \
     --note "ticket 06 concurrent routing" \
     --output .scratch/first-audio-latency/after-06-2026-10-30.json
   ```
3. 預期：general 類 `pre_answer` P50 ≈ 檢索時間且 ≤ 0.45 s（無 RAG 時接近 0）；`routing_hold` P50 接近 0，P95 不超過 `routing` − 首片段時間；general 首音較基準線約少一次路由時間（約 0.4–1.2 s，依 GPU 層數）。handoff 類：用戶端該輪聽到的第一段音訊是交接說明（`handoff=True` 且無主回答文字出現在控制台）；`rag_status` 出現 `timeout` 時控制台顯示「本輪未取得檢索」。
4. 在 `logs/llama-server.log` 確認同一輪的路由請求與主回答請求時間重疊（不同 slot id）。
5. 結果摘要補在本 Comments 後設 `Status: resolved`。

### 2026-10-30 實機量測（orchestrator）
`after-06-2026-10-30.json`（整合分支 39306c0）對照 `integration-2026-10-30-a.json`（未含 06）：
- 感知首音延遲 P50／P95：一般 3.58／4.08 → **2.57／2.95 s**；RAG 3.25／3.51 → **2.51／2.66 s**；交接 1.95／3.56 → 2.39／2.82 s。
- `pre_answer` P50 0.40 s、`routing_hold` 0；路由並行後本身變慢（0.69 → 1.09 s，與主回答共用 GPU），但已不在首音路徑上。
- **問題：檢索 24 輪中 22 輪 `timeout`**。RAGFlow 檢索本來就要 0.50–0.67 s，400 ms 上限幾乎每輪落空，等於關閉 RAG。待使用者決定（見 issue 15）。
- 交接 10 句中 8 句交接成功；2 句英文未交接，原因是 issue 07 的固定語系把英文當中文辨識（見 issue 07 Comments）。
