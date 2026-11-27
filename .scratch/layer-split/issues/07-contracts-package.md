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
