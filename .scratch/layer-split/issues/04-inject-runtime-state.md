<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# `server.state` 改為注入，並拆分訓練開始條件的檢查
Status: resolved
Blocked by: 01

依規格決定 6、14。

- 下列三處直接讀取核心的全域 `src.server.state`，改成由核心在建立物件時注入所需的值或回呼：
  - `src/llm/service.py`
  - `src/tts/training/gpu_guard.py`
  - `src/avatars/builder.py`
- 聲線訓練能否開始，拆成兩處檢查：
  - 核心在轉送「開始訓練」請求前，檢查目前有沒有舞台連線；
  - TTS 層只檢查剩餘顯存。
  - 訓練進行中，核心照現有規則拒絕新的舞台連線。介面上顯示的原因不變。
- 驗收：
  - `tests/test_training_jobs.py` 與相關路由測試全部通過；
  - 有舞台連線時無法開始訓練，顯存不足時也無法開始，兩種情況各有測試；
  - 刪除對應的例外清單條目。

## Comments

### 2026-11-26 完成

**改了什麼**

- **舞台連線檢查移到核心**：新增 `src/server/stage_guard.py`，放 `count_stage_connections`（讀 `state.avatar_streams`，含連線中的佔位）、`stage_connection_check` 與 `transcription_device`。`src/tts/training/gpu_guard.py` 只剩剩餘顯存的檢查；`choose_transcription_device` 的參數改為 `(read_vram, threshold_gb, cuda_available)`，不再知道舞台。
- **訓練開始條件**：`TrainingJobManager`（核心）的訓練前檢查使用核心的 `stage_connection_check` 加上 TTS 層的 `free_vram_check`。檢查順序、`id`、標籤與原因文字都沒變，介面顯示的原因不變。自動逐字稿由 `routes/tts_corpus.py` 的 `live_device_choice` 先由核心判斷舞台（有舞台就不跑 `nvidia-smi`），再交給 TTS 層判斷顯存。
- **`src/llm/service.py`**：`llm_response` 新增關鍵字參數 `published_config`，不再 import `src.server.state`。核心的兩個呼叫點（`voice_session` 的回答請求、`routes/audio.py` 的 `/asr`）呼叫時帶入 `state.config`。
- **`src/avatars/builder.py`**：`build_character` 新增 `loaded_vae` 回呼。核心的 `import_jobs.running_musetalk_vae` 提供正在執行的 MuseTalk 模型的 VAE，沒有時回傳 `None`，由建置器自己載入。
- `pyproject.toml` 刪除三條 `# ticket 04` 例外。

**測試**

- 新增 `tests/test_stage_guard.py`：舞台計數、舞台檢查，以及舞台優先且不探測 GPU。
- `tests/test_training_jobs.py` 新增：只有舞台連線、只有顯存不足時，各自都會拒絕開始訓練（409、不建立工作、不啟動子程序）。
- `tests/test_conversation_settings.py`：沒有全域 config 時，LLM 層使用核心帶入的已發佈角色。`tests/test_turn_lifecycle.py`：核心每次回答請求都帶入 `published_config`。
- `tests/test_avatar_import.py`：建置器沿用帶入的 VAE；`running_musetalk_vae` 只在 MuseTalk 已載入時回傳 VAE；匯入工作會把它交給建置器。
- CI 的每一步（`uv lock --check`、ruff、pyright、lint-imports、`scripts/check-integration.py`、pytest、web lint／test／build）全部通過。

**留意**

- 「訓練進行中，核心照現有規則拒絕新的舞台連線」：目前 `/offer`（`src/server/routes/webrtc.py`）**沒有**依訓練工作拒絕舞台連線的規則，訓練只在開始前檢查舞台。本工單維持現狀，沒有新增規則。若要落實規格決定 14 的這一句，需要另開工單（會動到路由，須依 ADR 0021）。
- 待維護者實機驗收：有舞台連線時開啟控制台「聲線訓練」的訓練前檢查，確認仍顯示「有 N 個舞台正在連線，請先關閉再重新檢查」且按鈕停用；關閉舞台後，在顯存不足時確認顯示剩餘顯存的原因。
