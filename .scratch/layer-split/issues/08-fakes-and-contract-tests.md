<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 各層的 fake 引擎與契約測試
Status: ready-for-agent
Blocked by: 07

依規格決定 15。

- 每一層都提供一個 `fake` 引擎：
  - STT 回傳固定文字；
  - LLM 回傳固定的口語文字增量與看板事件；
  - TTS 回傳指定長度的靜音 PCM；
  - 數位人渲染輸出固定畫面。
  - 透過設定即可選用，但不出現在控制台的引擎清單中。
- 每一層各有一組契約測試，驗證 adapter 的輸入輸出符合 `contracts/` 的模型與事件順序，包括取消時的行為。
- 核心的輪次、插話、交接測試改用 fake 引擎，不再各自手寫假物件。
- 需要 GPU 或真實模型的測試，統一用 pytest marker（例如 `gpu`）標記；GitHub CI 預設排除它們。
- 驗收：
  - 在沒有 GPU、沒有模型權重的機器上，`uv run --no-sync pytest` 全部通過；
  - 測試數量與覆蓋率不低於修改前，若有減少要說明原因。

## Comments

### 2026-11-27 TTS 層

分支 `ls/08-tts`。只做 TTS 層的 fake 引擎與契約測試；核心測試改用 fake 引擎留給後續步驟。

- `fake` 引擎（`src/tts/engines/fake.py`）回傳靜音 PCM，長度由片段的 `estimated_seconds` 決定（`synthesize` 會帶入；沒有或為 0 時，每個字 `SECONDS_PER_CHARACTER` = 0.1 秒）。
  - 即時路徑與真引擎相同：從 Matcha 抽出預取機制到 `src/tts/engines/prefetching.py` 的 `PrefetchingTTS`（佇列、epoch 丟棄、預取一段、播放柵欄、`TurnPCMEmitter` 事件），`MatchaTTS` 與 `FakeTTS` 都繼承它。Matcha 行為不變，既有 Matcha 測試未改。
  - 靜音會被 `StreamingSilenceTrimmer` 全部裁掉，所以 `TurnPCMEmitter` 新增選用參數 `trimmer`，fake 傳入不裁剪的版本，音框與片段事件才完整。
- 選用方式：設定檔或角色設定檔的 `tts.type: fake`。契約的 `TtsEngine` 加入 `"fake"`（`contracts/openapi/tts.json` 已重新產生）；`voice_library.CONFIGURABLE_TTS_ENGINES` 才包含 fake，控制台用的 `TTS_ENGINES`、引擎清單 `speech_snapshot`、音訊庫與目錄都不列出，也不能從控制台套用（`apply_tts_settings` 回「不支援」）。
- 契約測試 `tests/test_tts_fake_engine.py`（18 個）透過 `InProcessTtsService` 驗證：
  - 輸入輸出：`synthesize` 的 PCM 型式、長度、`max_seconds`、分塊；頻道每個音框為 320 樣本靜音，事件順序（`media_sequence`、`fragment_start`／`fragment_end`、`status`）與 `FragmentEnvelope` 一致。
  - 播放柵欄：片段播完前 `has_pending_work` 為真；沒有 turn 的片段不等柵欄。
  - 取消：`flush` 丟棄佇列與已預取的片段、停止正在送出的片段、新一輪照常播放；`accepts_media` 拒絕的舊輪次不播；worker 結束後不再開始新片段；預取只領先一段。
- 全部 CI 步驟通過：ruff、pyright、`lint-imports --no-cache`、`generate_openapi.py --check`、`check-integration.py`、pytest（2350 passed、2 skipped；本步新增 18 個測試）。沒有新增 `ignore_imports`。
- 尚未驗證：Matcha 預取的抽出沒有在實機（Edge／Matcha 對話、插話）驗證，只靠既有 Matcha 測試；首音延遲未量測。
