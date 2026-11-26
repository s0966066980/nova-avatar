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
