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

### 2026-11-26：第 2 步（TTS）

分支 `ls/07c-tts`。TTS 層依第 1 步的做法轉換，工單仍維持開啟，等 LLM 與數位人渲染完成。

- `nova_contracts.tts`：
  - 合成：`TtsVoice`（引擎與聲線、BreezyVoice 服務網址與模型 ID，全部是核心驗證過的 ID）、`TtsEngineSettings`（整個行程共用的音框率、Matcha 執行緒數、訓練的顯存門檻與 Whisper 大小）、`SynthesisRequest`（一個可播回覆片段一個請求，回傳 chunked 16 kHz s16le PCM）、`VoicePreparation`、`VoiceServerStatus`。
  - 音訊庫與聲線模型：`LibraryVoice`、`VoiceList`、`VoiceRef`、`VoiceUpload`、`TtsCatalog`、`VoiceModelPreview`（只接受三個預設句代碼）。
  - 聲線訓練：語料、逐字稿匯入、自動逐字稿、訓練工作、文字清單檢查、`training_activity` 等 DTO 與操作（`VoiceTraining`）。
  - `TtsService`（每個方法對應一個 HTTP 操作）、`HTTP_API` 與 `contracts/openapi/tts.json`；拒絕與失敗一律是 `TtsError`（訊息、HTTP 狀態與要附在回應的欄位）。
  - 只在同一行程使用的 `SpeechChannel`（一個會話的合成工作者，把 PCM 交給核心的 `AudioSink`）與 `TtsRuntime`（開啟頻道、啟動與關閉）。
  - `strip_visual_markup`：原本的 `sanitize_speech_text`。它不跳脫 HTML，依 CODING_STANDARDS 第 5 條改名。
- `src/tts/adapter.py` 的 `InProcessTtsService` 是唯一入口（另有 `config_section`），同時實作 `TtsService` 與 `TtsRuntime`。即時路徑不變：`SpeechChannel` 就是會話的引擎本身，外面只包一層薄薄的轉接，每 20 ms 音框仍由引擎自己的執行緒直接交給 `SpeakingAvatar`，沒有多出逐音框的複製或執行緒；Matcha 預取與插話時的 epoch 丟棄照舊。`synthesize` 在同一行程內只用於試聽，片段合成完畢才回傳 PCM。
- 聲線訓練工作從 `src/server/tts_training_jobs.py` 移到 `src/tts/training/jobs.py`，操作在 `src/tts/training/service.py`。依規格決定 14，舞台連線與管理者登入由核心檢查（`src/server/stage_guard.py`），TTS 層只回報顯存與其他檢查。訓練開始前核心先檢查舞台；TTS 層完成檢查後，核心會再數一次舞台連線，若期間有舞台連上就取消剛開始的工作並回 409。自動逐字稿遇到舞台連線時，由核心在請求中指定改用 CPU。
- 核心改用注入的服務：`app.py` 建立 `state.tts`／`state.tts_runtime`；`SpeakingAvatar(renderer, speech=...)`、`VoiceTurnSession(..., tts=...)`、`runtime_settings` 的 `speech_snapshot`／`current_snapshot`／`apply_tts_settings`／`preview_profile_voice`／`breezyvoice_server_ready` 以參數接收服務；音訊庫、訓練、語料路由都呼叫 `state.tts`；啟動時的 Edge 預熱與 BreezyVoice 啟動、伺服器關閉時的清理（訓練工作、Edge 共用連線、BreezyVoice 子行程）都經過服務。核心不再直接寫 `avatar.tts.config`：對話語系、招呼試播、角色切換都改用 `SpeechChannel.set_voice`。
- 設定相關的規則（設定檔與角色設定檔的 `tts` 段：引擎清單、來源 ID 檢查、逐字稿、聲線模型是否安裝、BreezyVoice 伺服器識別、載入時的遷移與通知）放在 `src/tts/config_section.py`。
- import-linter：新增 `tts-internals-private`。
- 測試：`tests/test_tts_contract.py`（DTO、轉接器、音訊庫、預熱、試聽、關閉、訓練操作）；核心測試改用注入的服務（`tests/tts_fakes.py` 的同行程服務、假的頻道與 runtime）。

與先前行為的差異：
- 音訊庫與語料的音檔改以一般回應送出，不再是 `FileResponse`，因此不支援 Range。
- 上傳的參考音訊先讀進記憶體（上限 20 MB），再交給 TTS 層；不再串流寫到音訊庫資料夾的暫存檔。
- 聲線模型試聽的停止條件改為服務自己的 60 秒期限；用戶端斷線不會提早停止合成，路由仍在 60 秒時回 504。
- 套用 BreezyVoice 時，若伺服器啟動失敗（找不到權重以外的原因），改回 503 並附上原因，不再是一般的 500。
- 訓練開始：舞台連線時直接拒絕，不再同時列出 Edge 文字清單的問題；開始後才偵測到舞台連線時，會取消工作並回 409。

待維護者實機驗收：
- 首音延遲：後端啟動後執行 `uv run --no-sync python scripts/measure_first_audio.py`，與 `layer-split` 合併前比較 P50／P95（規格決定 20：增加不超過 50／100 ms）。
- 舞台聆聽：Edge TTS 與 Matcha 各對話數輪，包括插話，確認聲音與嘴型同步、插話後沒有殘留的舊片段。
- 控制台：音訊庫的上傳、試聽、刪除；設定檔聲音試聽（Edge、BreezyVoice、Matcha）；聲線訓練的檢查清單、開始與取消，以及訓練進行中舞台會被拒絕。
