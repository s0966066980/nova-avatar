<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 主要 LLM 改為 Gemma 4 E2B
Status: ready-for-agent
Blocked by: 01, 03

依[規格](../spec.md)。`gemma-4-E2B_q4_0-it.gguf`＋`gemma-4-E2B-it-mmproj.gguf` 已在 `/home/oliver/llama/`，`src/llm/llamacpp.py:359,414` 已支援（附件視覺模型）。授權 Apache-2.0（Google 官方 `google/gemma-4-E2B-it-qat-q4_0-gguf`）。

- `config/config.yaml` 預設端點與模型改為 E2B；確認思考模式關閉、看板／口語協定與 GBNF（若適用）相容、路由 JSON 可解析。9B 保留為可選。
- 品質驗收：從 `logs/voice-test-history.json` 與知識庫挑 30 題（一般、RAG、天氣、需交接），9B 與 E2B 各答一次；自動檢查格式、簡體字、字數上限、路由正確率；產生並排報告（HTML 或 Markdown）給使用者決定。
- 路由正確率明顯低於 9B 時，加關鍵字初篩，不回頭用 9B。
- 以 issue 01 工具量測前後差異。

完成：報告交給使用者並在 Comments 記錄其決定；預設切換只在使用者接受後合併。

## Comments

### 2026-10-30 程式部分（分支 `fal/04-gemma-e2b`）

依指示**未切換預設模型**；`config/config.yaml` 只在 llm 區段註明 E2B 是可選的 llama.cpp 模型（與 9B 並列，mmproj 自動附掛），報告經使用者接受後才改設定檔／數位人設定檔的 `llm.model`。

**相容性確認與修改**
- 思考模式：從 GGUF 讀出的 Gemma 4 樣板以 `enable_thinking`（預設 false）控制 `<|think|>`，沒有「角色必須交替」的例外，支援 system 角色。llama-server 原本就以 `--reasoning off --reasoning-budget 0` 啟動並附掛 `gemma-4-E2B-it-mmproj.gguf`（新增測試鎖定）。另外 `src/llm/llamacpp_protocol.py` 新增 `thinking_request_fields()`：llamacpp 的回答與路由請求都帶 `chat_template_kwargs: {enable_thinking: false}`（LFM 2.5 除外），沿用外部啟動、沒加 `--reasoning off` 的伺服器時也不會思考。
- 看板／口語協定與 GBNF：E2B 走與 9B 相同的 `auto_reply_grammar`（無 `</think>` 外殼、溫度 0），測試確認。
- 路由 JSON：llamacpp 改用 `response_format: json_schema`（`ROUTE_SCHEMA`，route 列舉 answer／specialist／clarify 且排第一、其餘欄位必為字串），由文法保證可解析；其他 provider 仍用 `json_object`。解析時容許 ```` ```json ```` 圍欄與開頭空的思考區塊，`null` 欄位視為空字串；非決策文字仍拒絕。
- 品質評估工具 `scripts/eval_llm_quality.py`：`run` 對指定 llama-server URL 逐題執行正式程式路徑（`route_question`，再以預期目的角色的 `generate_response`、相同 Prompt、GBNF、知識庫片段或氣象資料作答），`report` 產生並排 Markdown（總覽、各類別路由、判讀、逐題）。自動檢查：協定格式（含看板 JSON）、疑似簡體字（OpenCC s2tw 逐字，排除里／后／台等正體共用字）、口語非空白字數 ≤ 角色 `response_max_chars`、模式與關鍵事實（有設定時）、路由正確率；E2B 路由比 9B 少 2 題以上即標示「加關鍵字初篩」。
- 題庫 `.scratch/first-audio-latency/e2b-eval/questions.json`：30 題＝一般 10、RAG 6、天氣 7、需交接 7。`logs/voice-test-history.json` 目前只有 1 筆提示（已收錄）；知識庫 `nova_rag` 只有文件「馬拉斯客灣」（內容「位於m87星雲」，10/30 快照固定為檢索片段）；其餘取自 10/29 反向交接路由探測與角色主題。

**驗證**：`tests/test_gemma_e2b.py` 8 項、`tests/test_llm_quality_eval.py` 11 項（含假 OpenAI 相容伺服器的端到端執行與 CLI）、`tests/test_llamacpp.py` 新增 1 項。ruff、pyright、`check-integration.py` 通過；全套 pytest 1152 passed、3 skipped，另 2 項失敗為 worktree 缺本機資產的已知基準失敗。

### 待實機驗證（orchestrator 依序執行；Status 維持 ready-for-agent）

顯存目前只剩約 2.4 GB，兩個模型都要在獨立埠 18080 各載入一次（9B 約需 5.9＋2 GB，E2B 約 3.2＋0.9＋KV GB），需在可占用 GPU 的時段執行；每次只開一個。以下在合併後的主 checkout 執行（在 worktree 執行時加 `--profiles /home/oliver/nova-avatar/config/avatar_profiles.yaml`）。

1. 啟動 9B（參數同 `ensure_server`）：
   ```
   cd /home/oliver/llama/llama.cpp/build/bin && LD_LIBRARY_PATH=$PWD:/usr/local/cuda/lib64 \
     ./llama-server -m /home/oliver/llama/Qwen3.5-9B-UD-Q4_K_XL.gguf --host 127.0.0.1 --port 18080 \
     -c 8192 -t 20 -b 2048 -ub 512 -fa on -ctk q8_0 -ctv q8_0 --reasoning off --reasoning-budget 0 -ngl 99 \
     > /home/oliver/nova-avatar/logs/llama-eval-9b.log 2>&1 &
   ```
   等 `curl -s http://127.0.0.1:18080/health` 回 `{"status":"ok"}`。
2. 評估 9B：
   ```
   cd /home/oliver/nova-avatar
   .venv/bin/python scripts/eval_llm_quality.py run --base-url http://127.0.0.1:18080/v1 \
     --label Qwen3.5-9B --output .scratch/first-audio-latency/e2b-eval/results-qwen3.5-9b.json
   ```
   每題印 `Qwen3.5-9B <id> route=<route> correct=<True|False>`，共 30 行；預期路由正確率與 10/29 探測同級（≥ 28/30）。
3. 停掉第 1 步的程序（只停自己啟動的 PID），啟動 E2B：
   ```
   cd /home/oliver/llama/llama.cpp/build/bin && LD_LIBRARY_PATH=$PWD:/usr/local/cuda/lib64 \
     ./llama-server -m /home/oliver/llama/gemma-4-E2B_q4_0-it.gguf \
     --mmproj /home/oliver/llama/gemma-4-E2B-it-mmproj.gguf --host 127.0.0.1 --port 18080 \
     -c 8192 -t 20 -b 2048 -ub 512 -fa on -ctk q8_0 -ctv q8_0 --reasoning off --reasoning-budget 0 -ngl 99 \
     > /home/oliver/nova-avatar/logs/llama-eval-e2b.log 2>&1 &
   ```
   確認日誌沒有 flash attention／KV 量化錯誤（E2B 的 head dim 為 512／256；若 `-fa on` 不被支援而啟動失敗，記錄錯誤後改 `-fa auto` 重試並回報，正式啟動參數需另改）；`curl -s http://127.0.0.1:18080/props | grep -o '"vision":[a-z]*'` 應為 `"vision":true`。
4. 評估 E2B：
   ```
   .venv/bin/python scripts/eval_llm_quality.py run --base-url http://127.0.0.1:18080/v1 \
     --label "Gemma 4 E2B" --output .scratch/first-audio-latency/e2b-eval/results-gemma-4-e2b.json
   ```
5. 停掉第 3 步的程序，產生報告：
   ```
   .venv/bin/python scripts/eval_llm_quality.py report \
     --baseline .scratch/first-audio-latency/e2b-eval/results-qwen3.5-9b.json \
     --candidate .scratch/first-audio-latency/e2b-eval/results-gemma-4-e2b.json \
     --output .scratch/first-audio-latency/e2b-eval/report.md
   ```
   把 `report.md` 交給使用者，決定記在本 Comments（報告「使用者決定」一行）。判讀出現「加關鍵字初篩」時，依規格另開工作加初篩，不回頭用 9B。
6. 使用者接受後：主角色與天氣角色的 `llm.model` 改為 `gemma-4-E2B_q4_0-it`（控制台套用，或修改 `config/avatar_profiles.yaml`），重啟後端，日誌應出現 `--mmproj` 與 `-ngl 99`；再以 issue 01 工具量測切換前後：
   ```
   .venv/bin/python scripts/measure_first_audio.py --rounds 1 --warmup 1 \
     --note "Gemma 4 E2B ngl 99" --output .scratch/first-audio-latency/after-e2b-2026-10-30.json
   ```
   與 issue 01 基準線比較 general／rag／handoff 的 P50／P95。

### 2026-10-30 實機評估與使用者決定（orchestrator）
9B 與 E2B 各在 18080 單獨載入（無 MuseTalk）跑 30 題：路由 30/30 對 30/30；格式 29/29 對 29/29；關鍵事實 9/9 對 8/9（E2B 漏 w04 氣溫 26）；首句 15 字內 15/29 對 7/29；首個片段 P50 0.58 對 0.24 s、路由 P50 0.50 對 0.23 s。E2B 有 3 題原始輸出含簡體字（正式流程經 OpenCC s2twp）。E2B 顯存 3.1 GB（含 mmproj）。`-fa on` 啟動正常、`modalities.vision: true`。
**使用者決定：接受，切換為 E2B**（Q26）。預設已改 `config/config.yaml`；切換後量測見下一段。路由未低於 9B，不需關鍵字初篩。
