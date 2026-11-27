<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 建立 `contracts/` 與各層介面
Status: resolved
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

### 2026-11-26：第 2 步（數位人渲染）

分支 `ls/07d-avatar`。渲染器依規格決定 1 留在核心行程內，所以 `nova_contracts.avatar` 沒有 `HTTP_API`，也不產生 OpenAPI。

- `nova_contracts.avatar`：
  - `AvatarService`：整個行程共用的部分，包含模型與人物素材載入、建立渲染器、轉場影片解碼、人物素材目錄（列出、可否啟動、綠幕、預覽、回收桶）、從影片匯入、嘴型畫質、輸出尺寸、錄影目錄，以及舞台背景。
  - `AvatarRenderer`：每場對話一個，包含 `put_audio_frame`、`accepts_media`、`flush_talk`、`is_speaking`、`direct_audio_enabled`、`asset_epoch`、`notify`、`render`、媒體柵欄與待播 PCM 的設定、直送音訊、角色素材切換（`bind_profile`）、角色轉場（`reset_role_presentation`、`ensure_role_presentation`、`begin_role_transition`、`start_role_transition`、`close_role_transition`），以及錄影。
  - DTO：`AvatarBootCheck`、`FrameSize`，以及舞台畫布 `STAGE_FRAME`（720×1280）與 `STAGE_FPS`（25）。載入後的模型與素材是不透明的 handle，核心只保存、原樣交回。
- 入口 `src/avatars/adapter.py`：`InProcessAvatarService` 與 `create_avatar_service()`。各層函式在呼叫時才從模組取得，所以測試替換 `catalog.avatar_bootable` 等函式仍然有效。層內的拒絕（人物素材目錄的 `ValueError`、`SceneError`、`QualityError`、`BuildError`）一律轉成訊息相同的 `ServiceError`。
- 綠幕合成：`RolePresentation`、`fit_frame` 與轉場影片解碼（`_VideoReader` 改名 `TransitionClipReader`）從 `src/profiles/media.py` 搬到 `src/scene/role_presentation.py`。核心只保留轉場影片庫（`TransitionMedia`），由核心決定播哪段、何時開始，畫面合成在渲染器內。渲染迴圈把原本內嵌的「角色畫布或綠幕場景」合成抽成 `BaseAvatar._present_frame`，程式碼不變，也沒有多複製影格。
- `SpeakingAvatar` 移除 `__getattr__` 轉發與 `config`／`_role_presentation` 的屬性轉寫。核心改用 `avatar.renderer.<方法>` 明確呼叫，`renderer` 的型別是 `AvatarRenderer`。`SpeakingAvatar` 只保留 TTS 配對需要的方法，以及明確的 `config`（讀寫渲染器上的 config）、`sessionid`、`notify`。`speaking_avatar.py`、`routes/video.py`、`import_jobs.py` 開啟 pyright 的 `reportAttributeAccessIssue`，打錯渲染器或服務的方法名稱時型別檢查會失敗。
- 核心：`app.py` 在啟動時建立 `state.avatar_service`，並以參數傳給 `current_snapshot`、`video_output_snapshot`、`apply_video_settings`、`apply_stage_background`、`apply_avatar`、`apply_mouth_quality`、`build_speaking_avatar`；路由與匯入任務則經由 `state.avatar_service` 使用。`import_jobs.running_musetalk_vae` 改為 `running_avatar_model()`，回傳（引擎類型、模型），挑出 VAE 的工作移到轉接器內。核心改用 `src.utils.avatar_ids.is_safe_avatar_id`。
- import-linter：新增 `avatar-internals-private`，保護 `src.avatars`、`src.scene` 除了 `adapter` 與 `config_section` 以外的所有模組，共 10 條契約全部通過。
- 行為差異：
  - `archive_avatar`、`archive_background` 改為回傳封存名稱，API 的 JSON 不變。
  - WebRTC 清理時直接呼叫 `renderer.discard_recording()`，不再先用 `getattr` 檢查；所有渲染器都有這個方法。
  - 轉場影片無法播放時丟出 `ServiceError`，不再是 `ProfileError`；呼叫端原本就接住所有例外並改用淡入淡出。
  - `BaseAvatar` 新增 `render`／`bind_profile`，會丟出 `NotImplementedError`，實際實作在 MuseTalk。
  - 每一幀多一次 Python 方法呼叫（`_present_frame`）。
- 測試：新增 `tests/test_avatar_contract.py`，共 13 項，涵蓋 DTO、渲染器符合 Protocol、角色轉場經由渲染器保持舊畫面再開始、沒有角色畫布時影格直接通過，以及轉接器的人物素材目錄、錯誤轉換、尺寸、匯入沿用執行中的 VAE。`tests/test_speaking_avatar.py` 改為斷言沒有隱式轉發。其他核心測試只換成假的或真的 `AvatarService`，並讓假的會話數位人帶 `renderer`；媒體序號、柵欄、嘴型連續、待機返回與綠幕合成的斷言都沒有放寬。`tests/test_layer_entry_points.py` 也涵蓋 `avatar-internals-private`（模組全數受保護、套件 `__init__` 不再匯出）。全部測試 2276 passed、2 skipped；ruff、pyright（0 errors）、lint-imports（10 條契約）、`generate_openapi.py --check`、`check-integration.py`、`uv lock --check` 都通過；`web/` 沒有變動，所以未重跑前端步驟。
- 留給後續：
  - `state.model`／`state.avatar`（不透明 handle）仍由核心保存，`AvatarService` 沒有 `health`／`apply_engine`，因為它不會拆成獨立行程。
  - TTS 的聲線切換（`avatar.tts.config = ...`）和 LLM 每輪的狀態（`_reply_rules_snapshot` 等）屬於另外兩位實作者的範圍，這次沒有動。

待維護者實機驗收（數位人渲染）：在舞台開啟綠幕 MuseTalk 角色，確認以下項目與修改前相同。

1. 待機畫面與背景合成正常，在控制台切換舞台背景時會淡入。
2. 長回覆期間嘴型連續，回答結束後回到待機時沒有跳格。
3. 設定兩個以上的角色後觸發交接，確認影片轉場與特效轉場都在共同起點才開始，結束後新角色正確。
4. `/record` 能開始並停止錄影，`/download` 可以下載錄好的檔案。
5. 控制台匯入一段閉嘴影片，確認製作完成。

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
- 測試：新增 `tests/test_llm_contract.py`（DTO、SSE 事件標記、adapter 的回覆、取消、審查、容量錯誤、交接、招呼、天氣、記憶與 llama-server 錯誤對應）與 `tests/llm_fakes.py`（核心測試用的 `FakeLlm`：除 `reply` 外都是真的 adapter）；核心測試改成以 `FakeLlm` 腳本化模型的回答。腳本 `scripts/replay_voice_baseline.py`、`scripts/benchmark_streaming_vs_legacy.py` 也改用同樣的做法。全部測試 2284 passed、2 skipped；與 `layer-split`（已含 TTS 與數位人渲染）合併後 2332 passed、2 skipped；ruff、pyright（0 errors）、lint-imports（11 條契約）、`generate_openapi.py --check`、`check-integration.py`、`uv lock --check` 都通過，`web/` 沒有變動所以未重跑前端步驟。

待維護者實機驗收：首音延遲（每個片段多一次行程內審查呼叫，量測約 0.03 ms，但實機首音仍須在場域主機確認）、啟動時自有 llama-server 的啟動與關閉（含 Ctrl-C）、控制台切換模型後既有對話跟著更新，以及交接與天氣問答照常。

### 2026-11-27：整合驗收

STT、TTS、數位人渲染、LLM 四個步驟都已合進 `layer-split`，工單關閉。整合分支上獨立重跑 CI 每一步：`uv lock --check`、ruff、pyright（0 errors）、`lint-imports --no-cache`（11 條契約全保持、沒有 `ignore_imports`）、`generate_openapi.py --check`（`llm.json`、`stt.json`、`tts.json` 皆為最新）、`check-integration.py` 通過；pytest 為 2332 passed、2 skipped、63 subtests passed。`web/` 沒有變動，未跑前端步驟。

實機驗收仍待維護者在場域主機確認，項目見各層步驟的留言（首音延遲、嘴型同步、自有 llama-server 啟停、聲線訓練與舞台拒絕等）。
