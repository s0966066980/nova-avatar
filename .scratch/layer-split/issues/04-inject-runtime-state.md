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

- 2026-11-27：完成。
  - `src/llm/service.py`：`llm_response` 新增 `published_config`，由核心（`VoiceTurnSession`、`routes/audio.py`）傳入 `state.config`，LLM 層不再讀 `server.state`。
  - `src/avatars/builder.py`：`build_character` 新增 `vae_provider`，核心的 `import_jobs.live_musetalk_vae` 借出執行中舞台的 VAE；沒有可借時才載入新的。
  - `src/tts/training/gpu_guard.py`：`choose_transcription_device` 的 `stage_connections` 改為必填；`count_stage_connections` 搬到核心的 `src/server/stage_connections.py`。TTS 層只讀剩餘顯存（`free_vram_check`），核心在 `evaluate_preflight` 與轉錄裝置選擇時一併檢查舞台連線，既有的兩種阻擋都還有測試（`tests/test_training_jobs.py`、`tests/test_training_gpu.py`）。
  - 已刪除 3 條例外；目前只剩 06 的 5 條。
- 「訓練進行中核心拒絕新的舞台連線」是原有行為，這張沒有改動。
