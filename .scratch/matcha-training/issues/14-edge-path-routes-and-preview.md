<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# Edge 路徑的路由缺口與三句預設試聽
Status: resolved

依[規格](../spec.md)第 2、13、17 點與工單 08 Comments 的「伺服器契約缺口」。工單 04、05、06 各自假設另一張負責 Edge 語料的建立與條文確認，結果沒有任何路由能做這兩件事，Edge 路徑在真實環境走不通。另外 `/api/speech/preview` 只念固定一句，三句預設試聽只剩中文可播。

- **建立 Edge 語料**：`POST /api/tts/corpora` 在 `source` 為 `edge-test-teacher` 時，直接以 `store.create(slug, source=SOURCE_EDGE_TEST_TEACHER)` 建立，不需要 `consent`（上傳來源的行為不變）。
- **記錄條文確認**：新增 `POST /api/tts/corpora/{slug}/acknowledgement`，body `{shown_text}`，呼叫 `record_acknowledgement`；文字與伺服器的 `MSA_CLAUSE.text` 不一致就拒絕。回傳確認時間與條文出處。
- **條文由伺服器提供**：`GET /api/tts/training` 的 `settings` 新增 `edge_clause: {reference, effective, text}`。介面（`web/src/components/voice-training/EdgeConfirm.vue` 與 `web/src/voiceTraining/api.js`）顯示並回傳這份伺服器文字，不得在前端另存一份英文條文；伺服器沒給就不能勾選確認。
- **三句預設試聽**：新增 `POST /api/tts/training/preview`，body `{voice_id, sentence}`，`sentence` 只能是伺服器定義的三個代號（中文、含數字的中文、英文），**不接受任何自訂文字**；用該聲線模型在 CPU 上以 sherpa-onnx 合成並回傳 `audio/wav`，有大小上限、沿用同一把合成鎖、不得阻塞事件迴圈；聲線模型不存在回明確錯誤。這不是下載模型，也不提供任何下載路由。完成畫面的三個試聽按鈕改用它。
- 所有新路由 ADMIN，登記 `ROUTE_ACCESS`；`tests/test_route_access.py` 通過。
- 測試：伺服器端用假的合成器與假的語料庫；前端補 `web/tests`（Node 22）。0 失敗、0 跳過，Python 與前端基準都不得新增失敗或跳過。
- 驗收的實機部分（真的 Edge 合成、真的試聽播放）留給工單 10。

## Comments

### 實作紀錄（分支 `mv2/14-edge-routes`）

所有新路由都是 ADMIN，已登記 `ROUTE_ACCESS`；`tests/test_route_access.py` 通過。回應沿用 `{"code": 0, "msg": "ok", "data": ...}` 與 `{"code": -1, "msg": 繁體中文原因}`，試聽成功時除外。

**`POST /api/tts/corpora`**：`source` 為 `edge-test-teacher` 時直接 `store.create(slug, source=...)`，不看 `consent`，回傳同一份語料摘要（`usage_label` 為 `Development only`）。其他來源行為不變。slug 重複 409；Edge 語料仍不接受上傳音檔（409）。

**`POST /api/tts/corpora/{slug}/acknowledgement`**：body `{"shown_text": "<條文>"}`，呼叫 `record_acknowledgement`。回傳 `{"acknowledged_at", "clause_reference", "clause_effective"}`。`shown_text` 不是字串或與 `MSA_CLAUSE.text` 不一致 400、什麼都不寫；語料不存在 404；非 Edge 語料 409。重複確認回傳第一次的時間。

**`GET /api/tts/training`**：`settings.edge_clause = {reference, effective, text}`，取自 `MSA_CLAUSE`。

**`POST /api/tts/training/preview`**：body 必須剛好是 `{"voice_id", "sentence"}`；`sentence` 只能是 `zh`、`digits`、`en`（文字定義在 `src/tts/voice_preview.py` 的 `PREVIEW_SENTENCES`），多一個欄位（例如 `text`）或其他代號都是 400，不會進到合成器。成功回 `200 audio/wav`（單聲道 PCM16、模型原生取樣率），標頭 `Cache-Control: no-store`、`X-Content-Type-Options: nosniff`，沒有 `Content-Disposition`。錯誤：聲線模型不在 `models/tts/` 清單 404；模型載入失敗、合成沒有音訊、超過 30 秒上限 500；合成超過 60 秒 504。沒有任何下載或匯出路由。

**合成方式**：重用 `matcha.resolve_voice_model` 與 `matcha.load_voice_model`（同一份已載入的模型，不會載入第二份），並從 `MatchaTTS._synthesize` 抽出模組層級的 `generate_speech` 與 `limit_peak`，引擎與試聽共用同一把每模型鎖與同一套正規化、峰值限制。CPU（`provider="cpu"`）、執行緒數取目前設定的 `matcha.num_threads`。路由用 `asyncio.wait_for(asyncio.to_thread(...))`，逾時或用戶端斷線時設定停止旗標，讓 sherpa-onnx 的 callback 回 0 中止生成。逾時捕捉 `asyncio.TimeoutError`（Python 3.10 與 3.11 都對；3.10 的它不是內建 `TimeoutError`）。

**前端**：`web/src/voiceTraining/constants.js` 不再有 `MSA_CLAUSE`；`store.loadEdgeClause()` 在進入 `edge-confirm` 畫面時向 `GET /api/tts/training` 取條文，`VtEdgeConfirm.vue` 顯示 `state.edgeClause`，確認時原文送回。伺服器沒給條文時顯示說明、核取方塊停用、不能繼續（`edgeConfirmGate` 新增 `clause` 原因，三份 locale 補字串）。確認時伺服器回 400（條文已被改寫）會重新取條文並取消勾選。完成畫面三個試聽按鈕改呼叫 `api.previewVoice(voiceId, key)`，以 Blob 的 object URL 播放，不再走 `/api/speech/preview`；`done.previewUnavailable` 的文字改成「沒有聲線模型時」的說明。`web/tests/fixtures/settingsApi.js` 的假後端補上 `edge_clause`。

### 用假物件驗證了什麼

- 伺服器：Edge 語料建立與確認路由、確認紀錄檔內容、不一致條文不寫入；`settings.edge_clause`；試聽的代號白名單、欄位白名單、`audio/wav` 與標頭、404／500／504 對應、合成不阻塞事件迴圈、逾時會通知合成執行緒停止；用假的 sherpa-onnx 模組與固定的聲線模型目錄驗證試聽與引擎共用同一個已載入模型（兩種建立順序都只載入一次）、等同一把鎖、CPU 與執行緒數、取樣率、峰值限制、超過上限與靜音的處理、取消；`tests/test_voice_preview.py` 另外守住前端三句文字等於伺服器的 `PREVIEW_SENTENCES`，且 `web/src` 裡沒有 MSA 條文的副本。
- 前端：API 用戶端、store（條文來自伺服器、原文送回、沒有條文不能確認、條文改寫後重取、三句試聽與錯誤、object URL 釋放）、`VtEdgeConfirm` 與 `VtDone` 元件、三份 locale 的鍵。

### 工單 10 必須實機驗證

- 真的 `POST /api/tts/corpora`（`edge-test-teacher`）後，真實伺服器上確認條文 → 真的 Edge 合成能開始（`require_acknowledgement` 通過）。
- 用真的訓練完成的聲線模型，三個試聽按鈕都真的播出聲音：中文、含數字的中文（`2026年11月24日`、`150元` 是否念對取決於模型目錄有沒有 `date-zh.fst`／`number-zh.fst`）、英文。
- 試聽與正在進行的真實回覆同時發生時，兩者輪流使用同一把鎖，回覆沒有被明顯拖慢；第一次試聽載入模型的耗時是否在 60 秒內。
- 瀏覽器端 `blob:` 播放（`<audio autoplay>`）在目標瀏覽器的自動播放政策下是否真的出聲。
- 全程 `CUDA_VISIBLE_DEVICES` 不影響試聽（只用 CPU）。

### 驗證結果

- Python（`uv lock --check`、ruff、pyright、`check-integration.py`、pytest）：ruff、pyright、整合檢查通過；pytest 基準 2 failed、2239 passed、3 skipped；本分支 2 failed（同樣的 PDF OCR 與 role coordinator）、2308 passed、3 skipped；新增測試 0 失敗、0 跳過。`python3.10 -m py_compile` 通過。
- 網頁（Node 22）：基準 348 pass、0 fail、0 skip；本分支 `npm run lint` 通過、357 pass、0 fail、0 skip、`npm run build` 通過。

### 未解決

- 試聽沒有並行上限：連點會排隊在同一把鎖上，每個請求各佔一條 worker 執行緒，逾時後會被通知停止。管理者單人使用，暫不另設單飛限制。
- 前端 `PREVIEW_SENTENCES` 的文字仍是一份顯示用副本（由測試守住與伺服器一致），沒有改成由伺服器提供。
