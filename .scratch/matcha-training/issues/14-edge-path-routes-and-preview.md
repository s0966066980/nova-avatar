<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# Edge 路徑的路由缺口與三句預設試聽
Status: ready-for-agent

依[規格](../spec.md)第 2、13、17 點與工單 08 Comments 的「伺服器契約缺口」。工單 04、05、06 各自假設另一張負責 Edge 語料的建立與條文確認，結果沒有任何路由能做這兩件事，Edge 路徑在真實環境走不通。另外 `/api/speech/preview` 只念固定一句，三句預設試聽只剩中文可播。

- **建立 Edge 語料**：`POST /api/tts/corpora` 在 `source` 為 `edge-test-teacher` 時，直接以 `store.create(slug, source=SOURCE_EDGE_TEST_TEACHER)` 建立，不需要 `consent`（上傳來源的行為不變）。
- **記錄條文確認**：新增 `POST /api/tts/corpora/{slug}/acknowledgement`，body `{shown_text}`，呼叫 `record_acknowledgement`；文字與伺服器的 `MSA_CLAUSE.text` 不一致就拒絕。回傳確認時間與條文出處。
- **條文由伺服器提供**：`GET /api/tts/training` 的 `settings` 新增 `edge_clause: {reference, effective, text}`。介面（`web/src/components/voice-training/EdgeConfirm.vue` 與 `web/src/voiceTraining/api.js`）顯示並回傳這份伺服器文字，不得在前端另存一份英文條文；伺服器沒給就不能勾選確認。
- **三句預設試聽**：新增 `POST /api/tts/training/preview`，body `{voice_id, sentence}`，`sentence` 只能是伺服器定義的三個代號（中文、含數字的中文、英文），**不接受任何自訂文字**；用該聲線模型在 CPU 上以 sherpa-onnx 合成並回傳 `audio/wav`，有大小上限、沿用同一把合成鎖、不得阻塞事件迴圈；聲線模型不存在回明確錯誤。這不是下載模型，也不提供任何下載路由。完成畫面的三個試聽按鈕改用它。
- 所有新路由 ADMIN，登記 `ROUTE_ACCESS`；`tests/test_route_access.py` 通過。
- 測試：伺服器端用假的合成器與假的語料庫；前端補 `web/tests`（Node 22）。0 失敗、0 跳過，Python 與前端基準都不得新增失敗或跳過。
- 驗收的實機部分（真的 Edge 合成、真的試聽播放）留給工單 10。
