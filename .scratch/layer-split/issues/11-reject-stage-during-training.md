<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 聲線訓練進行中拒絕新的舞台連線
Status: ready-for-agent
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
