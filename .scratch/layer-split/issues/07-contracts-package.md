<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 建立 `contracts/` 與各層介面
Status: ready-for-agent
Blocked by: 06

依規格決定 5、9、18 與 ADR 0028。

- 新增 `contracts/` 套件，有自己的 `pyproject.toml`，只依賴 Pydantic。
- 在 `contracts/` 定義：
  - 各層的請求與回應模型，以及串流事件，包括 LLM 的口語文字增量、看板、檢索參考、網頁來源、交接判斷結果，以及 TTS 的片段請求。
  - 各層的 Protocol：`SttService`、`LlmService`、`TtsService`、`AvatarRenderer`。
  - 常數 `CONTRACT_VERSION`。
- 把工單 02、03 暫放在其他位置的事件與片段型別移進來。
- 核心只透過 Protocol 呼叫各層。各層提供 in-process adapter 實作這些 Protocol。
- 依規格決定 7 的傳輸方式為 STT、LLM、TTS 產生 OpenAPI，提交到 `contracts/openapi/`。新增一支腳本重新產生 OpenAPI，CI 檢查產生結果與提交的版本一致。這時還不需要真的 HTTP 伺服器。
- 驗收：
  - 核心不再 import 任何處理層的內部模組，只依賴 `contracts` 和各層的 adapter 入口；
  - OpenAPI 一致性檢查納入 CI。

## Comments

### 2026-11-26：第 1 步（契約套件與 STT）

本工單拆成兩步，讓第 2 步可以依層平行進行。第 1 步（分支 `ls/07a-contracts-stt`）完成：

- 新增 `contracts/`：發行名稱 `nova-contracts`、匯入套件 `nova_contracts`（依工單 09 的 Q25），只依賴 Pydantic。根專案以 path 依賴引用並共用 `uv.lock`；CI 安裝步驟因為 `--no-sources` 而明列 `-e ./contracts`。
  - `nova_contracts`：`CONTRACT_VERSION = "1"`。
  - `common`：`ContractModel`（不可變、拒絕未知欄位）、`ServiceHealth`、`ErrorBody`、`ServiceError`。
  - `http`：`HttpApi`／`HttpOperation` 描述 loopback HTTP 形狀，`openapi_document` 由它產生 OpenAPI 3.1。
  - `stt`：`SttEngineSettings`、`SttPrepareRequest`、`TranscriptionOptions`、`Transcription`、`SttService` 與 `HTTP_API`（`GET /health`、`PUT /engine`、`POST /prepare`、`POST /transcribe`）。
  - `llm`：工單 02 暫放的 `SpokenDelta`、`SpeechEnd`、`SpeechEvent`（以 `type` 欄位區分）、`ReviewedFragment`、`SpeechSink`，以及 `FragmentReview` Protocol；`SpokenTextReview` 的實作留在 `src/llm/reply_events.py`。
  - `tts`：工單 03 暫放的 `PlayableFragment`、`FragmentEnvelope`、`AudioSink`；刪除 `src/utils/playable_fragment.py` 與 `src/tts/audio_sink.py`。
- STT 層完整轉換：`src/asr/adapter.py` 的 `InProcessSttService` 是唯一入口（另有 `config_section`），持有整個行程共用的辨識器，新引擎載入成功後才切換；`src/asr/__init__.py` 不再轉出任何名稱，`src/asr/prewarm.py` 移除。核心在 `app.py` 建立 `state.stt`，以參數傳給語音會話、`/asr` 與 `apply_stt_settings`。
- `scripts/generate_openapi.py` 依各契約模組的 `HTTP_API` 產生 `contracts/openapi/<層>.json`（目前只有 `stt.json`）；CI 新增 `--check` 步驟。
- import-linter：新增 `contracts-are-a-leaf` 與 `stt-internals-private`（protected：STT 內部只能由 STT 自己 import）；`tests/test_layer_entry_points.py` 確認每個已轉換的層沒有漏列的內部模組、套件 `__init__` 不轉出名稱。LLM、TTS、數位人渲染的位置已在 `pyproject.toml` 留好註解。
- 測試：新增 `tests/test_stt_contract.py`、`tests/test_contracts.py`、`tests/test_layer_entry_points.py`；核心測試改用假的 `SttService`。全部測試 2259 passed、2 skipped。

第 2 步：LLM（`LlmService`、回覆事件的 SSE、看板等事件）、TTS（`TtsService`、片段請求與 chunked PCM）、數位人渲染（`AvatarRenderer`）依同樣做法轉換，並各自產生 OpenAPI（渲染除外）。全部完成後才關閉本工單。

待維護者實機驗收：啟動後 `Startup prewarm:` 記錄的 `speech_input: True`、舞台免按對話的語音辨識，以及控制台切換 STT 模型（例如 small → turbo）後照常辨識。

### 2026-11-27：第 2 步（LLM）

分支 `ls/07b-llm`，依第 1 步（STT）的做法轉換 LLM 層（`src/llm`、`src/ragflow`、`src/web_search`，含工單 05 搬進來的交接判斷、天氣工具與 AI 招呼生成）：

- `contracts/nova_contracts/llm.py`：`LlmService` Protocol（35 個方法，每個方法對應一個 HTTP 操作）、請求／回應模型與 `HTTP_API`。
  - 回覆：`POST /reply` 以 SSE 串流 `ReplyEvent`（以 `type` 區分）：`ReplyStarted`（帶審查脈絡）、`ModelChunk`、`SpokenDelta`、`SpeechEnd`、`ReplyModeChosen`、`BoardStart`／`BoardItemShown`／`Board`、`ReplyDone`。LLM 只送口語文字增量與結構化事件；可播片段仍由核心切分（決定 12）。核心關閉串流即取消回覆；`ModelChunk` 是核心的 chunk 圍欄檢查點。
  - 片段審查：`POST /fragments/review`。審查狀態（`ReviewState`）由核心保管、隨每個片段送回，所以服務端不留逐回覆的審查狀態；網頁來源口語長度上限在這裡生效。
  - 每輪輸入（規則、助理設定、檢索內容、交接背景、天氣資料、網頁證據）全部隨請求攜帶；端點 URL、金鑰與模型目錄一律由核心依設定檔白名單解析後填入（CODING_STANDARDS 規則 1），服務端只收不解析。
  - 對話記憶仍由 LLM 層依核心的 session id 保管（`/sessions/...`：開始、提交、捨棄、清除、移除、選擇角色、歷史、記憶用量、保留上限、是否有紀錄），由核心決定何時提交或捨棄。
  - 交接判斷（`/handoff`）、AI 招呼（`/greeting`）、天氣（`/tools/weather`）、RAGFlow（`/ragflow/...`）、公開網頁搜尋（`/web/plan`、`/web/search`、`/web/summary`）、自有 llama-server（`/local-server...`）、預熱與 context 容量，也都經由 `LlmService`。
  - `contracts/openapi/llm.json` 由 `scripts/generate_openapi.py` 產生並已提交。
- `src/llm/adapter.py`：`InProcessLlmService` 是唯一入口（另有 `config_section`）。持有整個行程共用的對話記憶、routing 連線池與天氣快取；核心在 `app.py` 建立 `state.llm`，以參數傳給語音會話、`/asr`、角色協調器與設定套用。`src/llm/__init__.py` 不再轉出任何名稱。`config_section` 另外提供核心把設定檔轉成請求用的 `llm_settings`、`llm_session`、`reply_rules`、`local_server_settings`。
- 核心停止 import LLM 內部模組：
  - `voice_session`、`/asr`、設定套用、角色協調器（交接判斷、天氣、`select_profile`）、AI 招呼準備與 `routing` 都改呼叫 `LlmService`。
  - 屬於核心的資料搬出 LLM 層：網頁證據快取與 `public_result` → `src/server/web_evidence.py`；知識庫範圍與網頁存取政策的驗證與儲存（原 `src/ragflow/settings.py`、`selection.validate_selection`、`src/web_search/settings.py`）→ `src/profiles/knowledge_scope.py`；兩邊共用的 `join_spoken_fragments` → `src/utils/spoken_text.py`；回覆串流的核心端（`stream_reply`、`ServiceFragmentReview`）→ `src/server/reply_streaming/llm_reply.py`。
  - `BaseLLM.reply_events` 產生事件、`generate_response` 退成以同一組事件驅動的行程內封裝；回覆串流、看板、交接、天氣與招呼的行為不變。
- import-linter：新增 `llm-internals-private`（protected：LLM、RAGFlow、網頁搜尋的內部模組只能由這三個套件自己 import），取代工單 05 的 `core-uses-llm-entry-points`（已被涵蓋）；沒有新增任何 `ignore_imports`。`tests/test_layer_entry_points.py` 涵蓋 LLM 層。
- 測試：新增 `tests/test_llm_contract.py`（DTO、SSE 事件標記、adapter 的回覆、取消、審查、容量錯誤、交接、招呼、天氣、記憶與 llama-server 錯誤對應）與 `tests/llm_fakes.py`（核心測試用的 `FakeLlm`：除 `reply` 外都是真的 adapter）；核心測試改成以 `FakeLlm` 腳本化模型的回答。腳本 `scripts/replay_voice_baseline.py`、`scripts/benchmark_streaming_vs_legacy.py` 也改用同樣的做法。全部測試 2284 passed、2 skipped。

待維護者實機驗收：首音延遲（每個片段多一次行程內審查呼叫，量測約 0.03 ms，但實機首音仍須在場域主機確認）、啟動時自有 llama-server 的啟動與關閉（含 Ctrl-C）、控制台切換模型後既有對話跟著更新，以及交接與天氣問答照常。
