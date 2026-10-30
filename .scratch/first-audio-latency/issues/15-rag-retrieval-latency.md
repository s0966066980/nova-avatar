<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# RAGFlow 檢索速度
Status: resolved
Blocked by: 06

依[規格](../spec.md)與 [ADR 0022](../../../docs/adr/0022-run-routing-retrieval-and-answer-concurrently.md)。issue 06 實測（`after-06-2026-10-30.json`）：檢索上限 400 ms，24 輪中 22 輪 `timeout`；串行時期檢索本身 P50 0.50–0.58 s、P95 0.77–0.85 s。上限幾乎每輪落空，等於關閉 RAG。

- 拆解 `src/ragflow/client.py` 檢索請求的耗時：bge-m3 查詢嵌入（11435 Ollama）、Elasticsearch 檢索、RAGFlow 本身處理；在 Comments 記錄各段。
- 試可降低延遲的設定（嵌入常駐與暖機、`page_size`、關閉不需要的後處理、查詢嵌入快取），每項以 issue 01 工具量測。
- 依結果與使用者決定的取捨調整上限（見 Comments），並更新 ADR 0022 的數字。

## Comments

### 2026-10-30 實作與量測（分支 `fal/15-rag-retrieval`）

- **上限**：`RETRIEVAL_BUDGET_SECONDS` 0.4 → **0.7 s**（Q25）。新增測試：0.5 s 回來的檢索會被採用（舊 400 ms 下為 `timeout`）。ADR 0022 末尾補記，原 400 ms 敘述保留。
- **耗時拆解**（RAGFlow v0.27.2 CPU 版、知識庫 `nova_rag` 1 文件 1 chunk，30 句查詢；GPU 上有線上 Nova 伺服器但無進行中輪次）：

  | 段落 | P50 | P95 |
  |---|---|---|
  | 用戶端看到的檢索（3×30 句） | 0.58 s | 0.80 s |
  | RAGFlow 伺服器端總計（日誌，441 筆） | 0.52 s | 0.82 s |
  | ├ 驗證＋DB＋**bge-m3 查詢嵌入** | **0.48 s** | 0.77 s |
  | ├ Elasticsearch 兩次查詢 | 0.02 s | 0.03 s |
  | └ 其餘（斷詞、重排、回應） | 0.01 s | 0.02 s |
  | 空白問題（只有驗證與 DB） | 0.013 s | 0.018 s |
  | 直接呼叫 Ollama bge-m3 嵌入 | 0.49 s | 0.77 s |
  | 其中 Ollama `load_duration`（模型已常駐仍每次發生） | 0.13 s | 0.16 s |
  | 同一 GGUF 以 llama.cpp **純 CPU**（8 執行緒）嵌入 | **0.044 s** | 0.059 s |

  CPU 與 Ollama 向量餘弦相似度 1.0（同權重、結果相同）。耗時幾乎全在嵌入：bge-m3 與 MuseTalk、llama-server 共用 GPU，小 kernel 被時間切片拖慢；實際輪次中還與並行的路由 LLM 搶 GPU，預期更慢。
- **選項試驗**（各 30 句，P50／P95）：基準 0.60／0.79；`page_size` 1 0.53／0.80；`rerank_candidates_count` 4 0.59／0.85；`knn_top_k` 16＋`knn_num_candidates` 64 0.55／0.87；門檻 0 0.59／0.90；門檻 0.5 0.50／0.70（命中 8 → 2 句）；`include_knowledge_compilation` false 0.49／0.82；`vector_similarity_weight` 0.9 0.60／0.85；組合 0.60／1.11。全部在嵌入變異範圍內，不改用戶端參數。
- **未測／不可行**：`keyword` 會多一次 RAGFlow 聊天模型（qwen3.5:9b，Ollama GPU）呼叫，只會更慢且違反不載入 GPU 模型的規則；`rerank` 未設定模型，用戶端本就未送；兩者維持關閉。RAGFlow `/api/v1/retrieval`（`api/apps/restful_apis/chunk_api.py`）不接受用戶端提供的查詢向量，**用戶端查詢嵌入快取不可行**。結果快取只對逐字重複的問題有效，且知識庫更新後會給舊結果，不實作。暖機無效：bge-m3 已常駐（keep_alive −1），閒置後首次請求與一般請求相同。
- **上限覆蓋率**（GPU 無輪次負載，3×30 句）：≤0.4 s 22%、≤0.6 s 60%、**≤0.7 s 83%**、≤0.8 s 94%、≤1.0 s 99%。
- **量測事故**：第一次直接呼叫 Ollama 嵌入時漏帶 RAGFlow 使用的 `options.use_mmap=true`，觸發 bge-m3 重新載入 3 次（01:44 前後，每次 6–9 s，runner PID 90297 → 436316）。之後的請求一律帶相同選項與 `keep_alive: -1`，已不再重載，`expires_at` 仍為 2319 年（常駐）。期間若有線上檢索會逾時一次。
- **驗證**：ruff、pyright、`scripts/check-integration.py` 通過；pytest 1265 passed（僅已知 2 項 worktree 基準失敗）。未改 `web/`、`pyproject.toml`。

#### 提案（RAGFlow／嵌入服務端，未執行，需使用者同意）

1. **bge-m3 改在 CPU 執行**：預期嵌入 0.49 → 約 0.05 s、檢索約 0.1–0.15 s，並釋放約 1.3 GB VRAM。做法擇一：(a) 在 11435 的 Ollama 以 Modelfile `FROM bge-m3` + `PARAMETER num_gpu 0` 建立並取代 `bge-m3:latest`（RAGFlow 設定不變；需先實測 Ollama CPU 路徑是否同樣快，以及每次約 0.13 s 的 `load_duration` 是否仍在）；(b) 以 llama.cpp CPU 另起 OpenAI 相容嵌入服務並在 RAGFlow 註冊。向量相同，但 (b) 會改知識庫的嵌入模型設定，RAGFlow 可能要求重新解析文件。
2. 加速後以 issue 01 工具重測，依 `retrieval` P95 另定最終上限（預期可回到 ≤ 0.4 s），並再補記 ADR 0022。

### 待實機驗證

依實作指南不得重啟共用後端，`Status` 維持 `ready-for-agent`。步驟（合併本票後的程式碼）：

1. 以新程式碼重啟後端，關閉 kiosk 舞台頁後執行：
   ```
   cd /home/oliver/nova-avatar
   .venv/bin/python scripts/measure_first_audio.py --rounds 1 --warmup 1 \
     --note "ticket 15 retrieval cap 0.7 s" \
     --output .scratch/first-audio-latency/after-15-2026-10-30.json
   ```
2. 預期：`rag_status` 為 `timeout` 的輪次由 22/24 降到約 1/5 以下（離線 83% 在 0.7 s 內；實際輪次與路由搶 GPU，可能略差）；RAG 類 `pre_answer` P50 約 0.55–0.7 s，首音約多 0.3 s。若逾時仍過半，記錄 `retrieval` P50／P95 並優先處理上方提案 1。
3. 結果摘要補在本 Comments 後設 `Status: resolved`。

### 2026-10-30 嵌入服務補充量測（orchestrator）
同一台機器（MuseTalk＋E2B 已載入）以 30 句查詢量 bge-m3 `/api/embed`：
- 現行 11435 服務（GPU、systemd `CPUQuota=200%`）：P50 0.50／P95 0.70 s；Ollama 回報每次 `load_duration` 約 0.19 s（模型已常駐仍有）。
- 臨時 Ollama（GPU、無 CPU 配額，11499，測完已停）：P50 0.22–0.24／P95 0.27–0.30 s。CPU 配額約使嵌入時間加倍。
- 臨時 Ollama CPU-only（`CPUQuota=200%`）：P50 5.3 s，不可行。llama.cpp CPU 0.044 s（實作者量測）顯示瓶頸在 Ollama 每次請求的固定開銷。
提案（交使用者決定，未變更任何服務）：(a) 移除或放寬 `integrations/ragflow/nova-ragflow-embedding.service` 的 `CPUQuota`，檢索約可降到 0.25–0.3 s；(b) 改以 llama.cpp `llama-server --embedding` 提供 bge-m3（需把 RAGFlow 嵌入供應商改為 OpenAI 相容並重新驗證向量一致），檢索約 0.1 s。上限維持 0.7 s 直到決定。

### 2026-10-30 待使用者決定（orchestrator）
上限 0.7 s 下（`offset-split`）檢索等待 P50 0.57 s，是一般輪次最大的一段。嵌入服務提案 (a)／(b) 見上一段；選定後重測並定最終上限。

### 2026-10-30 使用者決定
選 (b)：改以 llama.cpp `llama-server --embedding` 在 CPU 上提供 bge-m3，RAGFlow 嵌入供應商改為 OpenAI 相容，停用 11435 的 GPU Ollama 嵌入服務以釋出約 1.3 GB 顯存；完成後依實測 P95 調低檢索上限。

### 2026-10-30 實作 (b)：llama.cpp CPU 嵌入（分支 `fal/15b-llamacpp-embedding`）

- **服務**：新增 `integrations/ragflow/nova-ragflow-llamacpp-embedding.service`（使用者層級、`CPUQuota=400%`、`MemoryMax=4G`）與 `scripts/ragflow_llamacpp_embedding.sh`：`CUDA_VISIBLE_DEVICES=""`、`-ngl 0`、4 執行緒、`--embedding --pooling cls`、上下文／批次 2048、`--no-webui`，只綁 Docker 橋接 `172.17.0.1:11437`（容器以 `host.docker.internal` 連入，已實測可達）。`nvidia-smi` 無此程序。
- **權重**：Ollama blob `sha256-daec91ff…3062c` 複製為 `models/ragflow/bge-m3-f16.gguf`（主 checkout，唯讀，sha256 相同）。`pull-model` 改為驗證後複製；GGUF 已通過驗證時不需 Ollama，內容不符則保留原檔並中止。
- **向量一致**：30 句查詢 llama.cpp 與 11435 Ollama 餘弦 min／mean／max 皆 1.000000；RAGFlow `/datasets/<id>/embedding/check`（已存向量）avg／min 1.0。單句嵌入：llama.cpp 4 執行緒 P50 0.047／P95 0.069 s（8 執行緒 0.041／0.061，取 4 減少與 Nova 搶 CPU）；Ollama GPU 0.35–0.47／0.65–0.88 s。CPU flash attention 無益。
- **長輸入**：557／1107／2207 token 各 2.5／5.4／12.8 s，RSS 至 3.5 GB；6.6k token 需 7.7 GB，主機可用 RAM 僅約 7 GB，故上限 2048（RAGFlow 預設切片 512），超過即 500 錯誤而非截斷（Ollama 會截斷）。已記入 `docs/ragflow.md`。
- **RAGFlow 切換**（新增 `ragflow.sh switch-embedding` → `ragflow_connection.py --switch-embedding`，以分支程式碼對線上 RAGFlow 執行，停用舊服務一步改為手動）：
  1. 備份 `/home/oliver/nova-avatar/.local/ragflow/backups/embedding-switch-20261030T034548512137Z.json`（0600；知識庫、文件清單、預設模型；第一次嘗試在建立執行個體前失敗，留下同內容的 `…034517676796Z.json`）。原值：`nova_rag` 嵌入 `32711c3eca0d11f1ae4c35070935da10`（`bge-m3:latest@bge-m3@Ollama`），預設嵌入同此 ID。
  2. 新增供應者 `OpenAI-API-Compatible`、執行個體 `nova-llamacpp`（`http://host.docker.internal:11437/v1`、API 金鑰 `x`：RAGFlow 的 OpenAI 用戶端拒絕空金鑰）→ 模型 ID `66683692d41411f19d3983244a6eddbc`。
  3. 向量比對通過後 `nova_rag` 改用新 ID；預設嵌入模型改為 `bge-m3@nova-llamacpp`。**未重新解析、未刪除文件**（v0.27.2 允許有切片時換模型）。
  4. 檢索經 llama.cpp 成功（伺服器日誌可見請求），之後 `systemctl --user stop` 並 `disable nova-ragflow-embedding.service`；disable 一併移除了 `~/.config/systemd/user` 的連結，單元檔仍在 repo。11435 已無監聽，GPU 上不再有 `ollama`（約 1.6 GB 釋出）。
  - 影響：RAGFlow 預設聊天模型 `qwen3.5:9b@bge-m3@Ollama` 掛在 11435，現已無法使用；Nova 只用檢索不受影響，需要時以 `connect-chat`／`unify-models` 改走 11434。
- **端到端檢索**（Nova 的請求內容，30 句 × 3，GPU 有線上 Nova 但無輪次）：

  | | P50 | P95 | 最大 | 命中 |
  |---|---|---|---|---|
  | 切換前（GPU Ollama） | 0.50 s | 0.68 s | 0.80 s | 6/90 |
  | 切換後 第 1 組 | 0.111 s | 0.150 s | 0.163 s | 6/90 |
  | 切換後 第 2 組 | 0.109 s | 0.146 s | 0.167 s | 6/90 |

  ≤0.2 s 100%、≤0.15 s 94–97%。
- **上限**：`RETRIEVAL_BUDGET_SECONDS` 0.7 → **0.3 s**（P95 0.15 s 的兩倍，低於 ADR 原始 400 ms）。測試先行：0.2 s 檢索會被採用；0.5 s（舊 GPU Ollama 速度）改為 `timeout`。ADR 0022、`docs/project-status.md`、`docs/x86-performance.md` 已更新。
- **腳本與文件**：`up` 一律啟動 llama.cpp 嵌入並等 `11437/health`（共用模式另等 11436）；`down`／`status`／`is-running` 改用新單元；`connect` 登記 `nova-llamacpp` 並在無預設時設為預設；`sync-models` 只加入聊天模型；`unify-models` 只統一聊天模型、知識庫仍用 Ollama 嵌入時拒絕執行、不再停用嵌入服務；`connect-chat` 程式不變（只處理聊天）。`docs/ragflow.md` 新增切換與「還原為 GPU Ollama 嵌入」章節；`docs/installation.md`、README、`THIRD_PARTY_NOTICES.md` 同步。
- **驗證**：ruff、pyright、`scripts/check-integration.py` 通過；pytest 1377 passed、3 skipped（僅已知 2 項 worktree 基準失敗）。未改 `web/`、`pyproject.toml`。

#### 合併到 main 後的收尾（暫時措施）

main 尚無啟動腳本，現行單元暫由本票 worktree 執行：`~/.config/systemd/user/nova-ragflow-llamacpp-embedding.service` 連到 worktree 的單元檔，另有 drop-in `nova-ragflow-llamacpp-embedding.service.d/10-until-main-merge.conf` 把 `ExecStart` 指向 worktree 腳本，worktree 的 `models/ragflow` 為指向主 checkout 的符號連結。**在 main 合併本票之前不要刪除此 worktree。** 合併後：
```
rm -r ~/.config/systemd/user/nova-ragflow-llamacpp-embedding.service.d
systemctl --user disable nova-ragflow-llamacpp-embedding.service
systemctl --user link /home/oliver/nova-avatar/integrations/ragflow/nova-ragflow-llamacpp-embedding.service
systemctl --user enable nova-ragflow-llamacpp-embedding.service
systemctl --user daemon-reload && systemctl --user restart nova-ragflow-llamacpp-embedding.service
curl --noproxy '*' -fsS http://172.17.0.1:11437/health
```
另外以新程式碼重啟後端後，可用 `scripts/measure_first_audio.py` 重量實際輪次的 `rag_status` 逾時率（預期接近 0）。
