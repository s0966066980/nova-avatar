<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 文件更新與最終驗收
Status: ready-for-agent
Blocked by: 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 15, 16

依[規格](../spec.md)。

- 以 issue 01 工具做最終量測，對照規格目標表，結果寫入 `docs/project-status.md`（取代 9 月的 1.19 s 基準，註明起點定義）。
- 更新 README、`docs/software-stack.md`、`docs/x86-performance.md` 中的 LLM、ASR、TTS 預設與延遲數字。
- 未達第二階段目標時，列出剩餘瓶頸與下一步。

## Comments

### 2026-10-30 Code review 修正（分支 `fal/review-fixes`）

- **RAGFlow 連線池**：`_shared_session` 換 loop 時、`close_shared_session` 關閉時，舊 loop 的 session 不再直接丟棄：舊 loop 仍可執行就排到它自己的 loop 上關閉，已關閉就在目前 loop 標記關閉。`_shared_session` 改為 async。
- **並行路由的結束路徑**：路由被取消（插話）、路由失敗、路由後輪次已過期、保留答案播放中被取消、讀取輸入時被取消，都會等候受保護的 LLM worker 結束並丟棄該輪 pending history（`_settle_speculation`）。路由失敗時先隔離舊答案（避免 TTS 卡在保留閘門），再以新世代回報錯誤。`worker: list` 改為 `HeldAnswer`，`(text, rag_result)` tuple 改為 `AnswerInputs`；輸入失敗另存 `input_error`。
- **語意等待計時器**：`active` 改查輪次即時狀態（與 `chunk_guard` 相同），模型在隔離後停住也不會釋放片段。
- **不穩定測試**：`VideoEnqueueStageTests` 改在 `record_video_data`（階段已記錄後）才設 `quit_event`，不改正式程式。4 執行緒 CPU 負載下迴圈 200 次：修正前 45/400 失敗，修正後 0/400。
- **英文首句規則**：en-US 的提示改為「at most 12 words」（`FIRST_SENTENCE_PROMPT_EN`、`first_sentence_prompt(locale)`，prewarm 同步傳入語系以保持前綴快取一致）；`eval_llm_quality.py` 英文首句以 `speech_units` 逐詞計。中文 15 字與看板模式上限不變。
- **小修**：`ANSWER_STAGES` 改為明列；llama.cpp「全部層」改用 `ALL_GPU_LAYERS`（`-ngl all` 亦對應此值）。
- 驗證：ruff、pyright、`check-integration.py` 通過；pytest 1305 passed、3 skipped（排除 2 個已知的工作樹基準失敗）。
