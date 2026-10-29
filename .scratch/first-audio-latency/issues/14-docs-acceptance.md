<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 文件更新與最終驗收
Status: ready-for-agent
Blocked by: 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 15, 16, 17

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

### 2026-10-30 文件更新（分支 `fal/14-docs`）

依 `final-2026-10-30.json`（3 輪 96 句，感知首音＝人聲結束 → 伺服器送出第一個可聽幀）與 `baseline-2026-10-30.json` 更新文件；未做任何實機或 GPU 操作。

- `docs/project-status.md`：9 月 1.19 s 基準改為「首音延遲實測（2026-10-30）」：四種起訖定義（基準線只有「用戶端收到」，另列同定義欄位對照）；一般／RAG／交接基準線與最終 P50／P95 對照規格目標（一般 2.00／2.22 s：P95 達第一階段，P50 與第二階段未達；RAG 2.00／2.28、交接 1.63／2.20 只有 P95 達標）；首音延遲與 Prompt 起算兩種起點；一般輪次各段組成與對應改動；剩餘瓶頸（檢索等待 0.56、靜音等待 0.32、首片段 0.42、片段到送出 0.36、Edge 開頭無聲段 0.10、VAD 拖尾 0.08、上行 0.09 s）與下一步、TTS 影響（BreezyVoice 2.48 s、Fun-CosyVoice3 1.77 s）、英文交接路由（issue 17 進行中，未修復）。9 月 soak 的非延遲 gate 改列為歷史。「場域用 FunASR」改為實際組合（Whisper small 中英偵測＋Gemma 4 E2B），註明 Q24／Q26；正式執行設定補 ASR、LLM、TTS、檢索上限；驗證狀態更新為本次測試數。
- `README.md`：對話鏈路改寫 ASR／LLM／TTS 預設並加首音延遲摘要；安裝表 LLM 列、BreezyVoice 段（2.5 s、顯存、聲音授權）、新增 Edge TTS 僅供開發說明、`measure_first_audio.py` 指引。
- `docs/software-stack.md`（維持英文）：STT 兩列、LLM 拆為 llama.cpp（E2B 預設、9B 可選）與 Ollama、Edge TTS 註明仍是執行預設、BreezyVoice 首片段約 2.5 s、Qwen3-TTS 已移除、首音延遲摘要、執行需求改為 llama.cpp。
- `docs/x86-performance.md`：新增「首音延遲改善（2026-10-30）」節（預設組合、三類別對照、一般輪次組成、本機 TTS 與顯存），註明 10 月 15–16 日舊節使用 9B＋FunASR、Prompt 起算；驗收節加量測工具。
- 未改：`.scratch/field-pilot/spec.md` 的凍結組合仍寫 FunASR／Qwen3.5-9B（規格紀錄，由使用者決定是否改）。
- 驗證：ruff、pyright、`check-integration.py` 通過；pytest 1305 passed、3 skipped（另 2 項為已知 worktree 基準失敗）；web lint、210 passed、build 通過。

仍待使用者決定或確認，`Status` 不設為 resolved：TTS 方向與 8 小時穩定性（issue 10）、嵌入服務與最終檢索上限（issue 15）、靜音等待／抖動緩衝／Edge 前導等選項（issue 16）、每輪啟動批次的嘴型同步目視確認（issue 13）、首片段後停頓試聽與看板口語 15 字限制（issue 08）、停用 11434 Ollama（issue 12）；英文交接路由修正後需重跑最終量測（issue 17）。
