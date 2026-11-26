<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# `server.state` 改為注入，並拆分訓練開始條件的檢查
Status: ready-for-agent
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
