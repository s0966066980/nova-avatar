<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 各層的 fake 引擎與契約測試
Status: ready-for-agent
Blocked by: 07

依規格決定 15。

- 每一層都提供一個 `fake` 引擎：
  - STT 回傳固定文字；
  - LLM 回傳固定的口語文字增量與看板事件；
  - TTS 回傳指定長度的靜音 PCM；
  - 數位人渲染輸出固定畫面。
  - 透過設定即可選用，但不出現在控制台的引擎清單中。
- 每一層各有一組契約測試，驗證 adapter 的輸入輸出符合 `contracts/` 的模型與事件順序，包括取消時的行為。
- 核心的輪次、插話、交接測試改用 fake 引擎，不再各自手寫假物件。
- 需要 GPU 或真實模型的測試，統一用 pytest marker（例如 `gpu`）標記；GitHub CI 預設排除它們。
- 驗收：
  - 在沒有 GPU、沒有模型權重的機器上，`uv run --no-sync pytest` 全部通過；
  - 測試數量與覆蓋率不低於修改前，若有減少要說明原因。

## Comments

### 2026-11-27 LLM 層

分支 `ls/08-llm`，只做 LLM 層（`src/llm`、契約的 `llm` 模組、LLM 測試），STT、TTS、數位人渲染由其他步驟處理。

- **`fake` 引擎**：`src/llm/engines/fake.py` 的 `FakeLLM` 只取代模型，依回覆協定串流固定內容（兩個 chunk：一句口語文字加兩項看板），所以協定解析、片段審查、看板事件與對話記憶都照真實路徑執行；完全離線，不連任何模型伺服器。可用 `answer_chunks(text)` 或自訂 `chunks` 寫腳本。
- **選用方式**：設定檔 `llm.engine: fake`（空白或未設定＝`openai-compatible`，即原本的 OpenAI 相容客戶端）。契約的 `LlmSettings` 新增 `engine` 欄位（預設 `openai-compatible`，OpenAPI 已重新產生），adapter 依每個對話的設定從 `ENGINES` 選引擎；`engine: fake` 時不啟動自有 llama-server，`prewarm` 直接回報就緒。未知的引擎名稱在載入設定時以 `ValueError` 拒絕。`fake` 不是端點，不在 `PROVIDERS` 或 `llm.endpoints`，控制台的端點清單看不到它（有測試確認）。
- **契約測試**：新增 `tests/test_llm_fake_engine.py`（11 個測試），對行程內 adapter 搭配 fake 引擎驗證：每個事件都能通過 `nova_contracts.llm` 模型的 JSON 往返；事件順序（`ReplyStarted` 最先、`ReplyDone` 最後，看板開始、項目、整體依序）；取消時回覆停止、不再產生事件、模型串流被釋放且沒有多讀下一個 chunk；輪次提交只入歷史一次、提交後不能捨棄、捨棄後不能提交且下一輪乾淨；以及經設定選用與不列入控制台清單。
- **`tests/llm_fakes.py`**：`reply_events()` 原本手寫事件序列，改為由 fake 引擎產生；其餘（腳本化的 `FakeLlm`、`answering`、`ask`）維持不變，核心測試沒有遷移，留待工單 08 的後續步驟。移除了沒人用的 `board_events()` 與 `reply_events` 的 `mode` 參數。
- 驗證：ruff、pyright（0 errors）、`lint-imports --no-cache`（11 條契約全保持、沒有 `ignore_imports`）、`generate_openapi.py --check`、`check-integration.py` 通過；pytest 2344 passed、2 skipped、63 subtests passed（整合分支為 2332，多出的 12 個為本次新增）。`web/` 沒有變動，未跑前端步驟；`uv lock --check` 沒有相依變動，未重跑。
- 已知限制：fake 引擎只取代回覆的模型呼叫；交接判斷、AI 招呼生成與網頁搜尋規劃仍使用真實的 OpenAI 相容客戶端，離線測試這些路徑時，需在測試中注入假的用戶端工廠（交接的關鍵字預篩選本來就不呼叫模型）。
