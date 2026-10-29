<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 第一句簡短的 Prompt 規則
Status: ready-for-agent
Blocked by: 04

依[規格](../spec.md)。第一個可播回覆片段需等完整句子（`src/server/reply_streaming/fragmenter.py`；逗號切分需 24 字以上且 0.5 s，0.5 s 只在新 token 到達時檢查）。

- 在回覆規則加入「以一句 15 字內的完整短句開頭」，不改完整語意邊界規則；以 E2B 驗證遵循率。
- 語意等待上限改為計時器觸發，不依賴新 token 到達。
- 量測第一個片段字數與時間；若仍不達標，在 Comments 提出放寬第一個片段邊界的方案（需改術語表與 ADR 0007，交使用者決定）。

## Comments

### 2026-10-30 程式部分（分支 `fal/08-short-first-sentence`）

- **首句規則**：`src/llm/reply_contract.py` 新增固定規則 `FIRST_SENTENCE_PROMPT`（`FIRST_SENTENCE_MAX_CHARS = 15`）：口語以一句 15 字內、以「。」「！」「？」結束的完整短句開頭，第一句不用逗號接長句。`compose_system_prompt` 在可編輯回覆規則之後附加，AUTO／SIMPLE／BOARD 都帶。採固定規則而非只改預設 Rule，因為主機兩個角色的已存 Rule（revision 4）是自訂文字，改預設不會生效。預設口語 Rule 拿掉「約 10–20 字」以免矛盾；口語與看板分工的正確範例縮為 14 字。分段器的完整語意邊界規則未改。
- **注意（交使用者知悉）**：GBNF 規定 BOARD 口語只能一句，所以看板模式的口語摘要實際也限 15 字內。主機角色已存 Rule「搭配看板時先用 50~200字以內說明」原本就與單句文法衝突，這次更明確；若希望看板摘要較長，需另決定（例如規則只限 SIMPLE）。英文語系沿用同一字數計法（字母逐字計），未另調。
- **語意等待改為計時器觸發**：`SemanticFragmenter.semantic_wait_remaining()` 加上 `SemanticWaitTimer`（`threading.Timer`；餵入、flush、逾時釋放共用一把鎖，順序不亂；`close` 後不再送出；輪次已被柵欄擋下時不釋放）。`BaseLLM.generate_response` 的串流路徑改用它，模型停頓時 24 字以上的子句會在 0.5 s 到期當下送出，不等下一個 token。`ReplyFragmentProducer`（async，正式路徑未使用）未改。
- **評估工具**（`scripts/eval_llm_quality.py`）：`check_answer` 新增 `first_sentence`（以正式分段器切出首句，須完整且 ≤ 15 字；字數＝字母、數字、漢字）。`run` 記錄每個 chunk 的到達時間，以正式 parser 與分段器（含語意等待計時）重播，得出 `first_fragment`（字數、秒數、文字）。`report` 增加「首句 15 字內且完整」「首個片段 P50」與逐題「首個片段」。新增 `first-sentence --results X.json` 單一執行摘要（遵循率、首個片段字數與時間 P50／P95、未遵循清單）；遵循率由 raw 重算，舊結果也適用。
- **驗證**：新增 `tests/test_first_sentence_rule.py` 8 項、`tests/test_reply_streaming.py` 6 項（計時釋放、未到期與關閉、柵欄後不釋放、`generate_response` 在下一個 token 前送出逗號子句）、`tests/test_llm_quality_eval.py` 3 項。ruff、pyright、`check-integration.py` 通過；全套 pytest 1213 passed、3 skipped，2 項失敗為 worktree 缺本機資產的已知基準失敗。

### 待實機驗證（orchestrator 執行；Status 維持 ready-for-agent）

1. **E2B 首句遵循率**：與 issue 04 第 3–4 步同一次執行即可，不必另跑（合併後 `run` 會自動記錄首句與首個片段）。E2B 在 18080 就緒後：
   ```
   cd /home/oliver/nova-avatar
   .venv/bin/python scripts/eval_llm_quality.py run --base-url http://127.0.0.1:18080/v1 \
     --label "Gemma 4 E2B" --output .scratch/first-audio-latency/e2b-eval/results-gemma-4-e2b.json
   .venv/bin/python scripts/eval_llm_quality.py first-sentence \
     --results .scratch/first-audio-latency/e2b-eval/results-gemma-4-e2b.json \
     --output .scratch/first-audio-latency/e2b-eval/first-sentence-e2b.md
   ```
   預期 `first-sentence-e2b.md` 顯示「遵循率：x/29」、首個片段字數 P50 ≤ 15。建議以 ≥ 26/29（約 90%）視為達標，由使用者確認。
2. **實機首個片段時間**：E2B 切換並重啟後端後（issue 04 第 6 步），以 issue 01 工具量測：
   ```
   .venv/bin/python scripts/measure_first_audio.py --rounds 1 --warmup 1 \
     --note "issue 08 first sentence + semantic timer" \
     --output .scratch/first-audio-latency/after-08-2026-10-30.json
   ```
   比較 `first_fragment` 階段（主回答開始到第一個可播回覆片段）與基準 P50 0.85 s／P95 1.27 s。

### 若仍不達標：放寬第一個片段邊界的方案（需改術語表與 ADR 0007，交使用者決定）

只對每輪**第一個**片段放寬：遇到逗號、冒號、分號且前段已是 8 字以上可獨立朗讀的子句時立即釋放（不等 24 字與 0.5 s），之後的片段仍守完整語意邊界。需在 `CONTEXT.md`「完整語意邊界」與 ADR 0007 加註「首個片段例外」。代價：第一片段後韻律重置，可能聽到短停頓；第一片段被柵欄或重試時需確認不重複朗讀。較保守的替代：只把第一片段的語意等待縮為 0.2 s。
