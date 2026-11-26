<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 聲線訓練進行中拒絕新的舞台連線
Status: resolved
Blocked by: 04

依規格決定 14（2026-11-26 維護者決定新增）。目前只在開始訓練前檢查舞台連線；訓練進行中，舞台仍可連上並使用 GPU，與訓練搶顯存。

- **核心**：`POST /offer` 收到舞台角色的 offer 時（判斷方式同 `src/server/access.py` 的 `offer_access`），若有訓練工作進行中（`TrainingJobManager` 的狀態，經工單 04 的 `src/server/stage_guard.py` 或同層模組判斷），回傳 409 和穩定的原因代碼 `voice_training_active`，不建立會話、不載入任何模型。
  - 控制台的 offer 不受影響。
  - 已經連上的舞台不會被中斷（開始訓練前已經檢查過舞台連線，正常情況下不會發生）。
  - 路由分類不變，`/offer` 仍依 ADR 0021 的 `offer_access` 判斷 stage／admin；不新增路由。
- **舞台畫面**（`web/src/stageConnection.js` 與相關元件）：收到 `voice_training_active` 時顯示繁體中文說明「聲線訓練進行中，數位人暫停服務」（其他語系也補上），並照現有的重連節奏自動重試；訓練結束後自動連上，不需要現場人員操作。不要把它當成一般錯誤一直跳錯誤訊息。
- **控制台**：聲線訓練頁的開始確認或進行中畫面，加一句說明「訓練進行中，舞台無法連線」，讓管理者知道後果。
- 訓練結束的所有路徑（完成、失敗、取消、行程異常結束）都要解除限制，有測試涵蓋。
- 驗收：
  - 訓練進行中，舞台 offer 得到 409／`voice_training_active`，控制台 offer 照常成功；
  - 訓練完成、失敗、取消後，舞台 offer 恢復成功；
  - 舞台畫面在收到這個代碼時顯示說明並自動重試（前端測試）；
  - `tests/test_route_access.py` 仍通過，路由分類不變；
  - CI 全部通過；
  - 待維護者實機驗收：開始一次短訓練，舞台顯示說明；取消訓練後舞台自動恢復。

## Comments

### 2026-11-26 完成

**改了什麼**

- **核心**：`TrainingJobManager.job_active()` 回報是否有訓練工作佔著 GPU（`running` 或 `cancelling`；完成、失敗、取消後即為否）。`src/server/stage_guard.py` 新增 `stage_offer_refusal(role, training)` 與穩定原因代碼 `voice_training_active`：舞台角色的 offer 在訓練進行中回 409 `{"code": -1, "reason": "voice_training_active", "msg": "聲線訓練進行中，數位人暫停服務"}`；控制台 offer 不受影響。
- **`POST /offer`**（`src/server/routes/webrtc.py`）：讀完請求後先正規化 `client_role`，再經 `request.app[MANAGER_KEY]` 詢問 `stage_offer_refusal`；被拒時不保留會話、不建立數位人、不載入模型。路由分類不變（仍由 `offer_access` 判斷 stage／admin），沒有新增路由。
- **縮小競態**：`TrainingJobManager.start` 在登記工作的鎖內，除了原本的其他訓練工作與自動逐字稿，也重新檢查舞台連線；預檢後才連上的舞台仍會擋下訓練。
- **舞台畫面**：`web/src/stageConnection.js` 新增 `isVoiceTrainingPause` 與說明文字；`stage.html` 收到這個代碼時顯示「聲線訓練進行中，數位人暫停服務／訓練結束後會自動連線，請稍候。」（非錯誤樣式、無重試按鈕、kiosk 與一般舞台相同），照 `kioskReconnectDelayMs` 的節奏自動重試；重試期間保留這段說明，不閃回「連線中」。英文由 `stageLocale.js` 提供。
- **控制台**：聲線訓練的訓練前檢查畫面與進行中畫面加上「訓練進行中，舞台無法連線；訓練結束後舞台會自動恢復。」（zh-TW／zh-CN／en-US）。

**測試**

- `tests/test_webrtc_lifecycle.py`：訓練中舞台 offer 得 409／`voice_training_active` 且沒有會話、數位人、peer；控制台 offer 照常成功；訓練完成、子程序異常結束（失敗）、工作執行緒拋例外（失敗）、取消後，舞台 offer 恢復成功。
- `tests/test_training_jobs.py`：預檢之後才連上的舞台仍擋下開始訓練。
- `web/tests/stage-voice-training.test.js`：一般舞台與 kiosk 顯示說明、無重試按鈕、依重連節奏重試，訓練結束後自動連上；重試中不閃回「連線中」；其他 409 維持原行為；英文文字。`web/tests/voice-training-components.test.js`：訓練前檢查與進行中顯示說明，結束後不顯示。
- CI 每一步（`uv lock --check`、ruff、pyright、lint-imports、`scripts/check-integration.py`、pytest（含 `tests/test_route_access.py`）、`npm audit --omit=dev`、web lint／test／build）全部通過。

**留意**

- 仍有極小的競態：舞台 offer 檢查「沒有訓練」與保留會話之間，若訓練工作恰好在另一執行緒登記，兩者可能同時成立。視窗只有幾個同步指令，本工單不另加跨執行緒鎖。
- 重試期間舞台每次都會重新取麥克風並送 offer（沿用既有重連流程），訓練一次約 40–60 分鐘，最慢每 10 秒一次。
- 待維護者實機驗收：在控制台開始一次短訓練，確認舞台（`/stage.html?kiosk=1` 與一般開啟）顯示「聲線訓練進行中，數位人暫停服務」且不跳錯誤；按「取消訓練」後，舞台在 10 秒內自動連上，不需要現場人員操作。
