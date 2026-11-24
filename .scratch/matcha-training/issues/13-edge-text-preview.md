<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# Edge 文字清單：合成前校對
Status: resolved

依[規格](../spec.md)第 7、13 點與介面原型。工單 06 的 `POST /api/tts/training/start` 直接收 `sentences`，數字展開後有未解決項的句子會等到合成後才進入「待確認」，管理者白白花了 Edge 請求才發現。決定 13 要求：Edge 的上傳文字檔要在**合成前**校對（內建句庫免校對）。

- 新增 `POST /api/tts/training/text-preview`（ADMIN，登記 `ROUTE_ACCESS`），body `{sentences: string}`（與 start 相同的格式與限制，沿用 `parse_text_list`），回傳逐句 `{index, text, spoken, unresolved: [...]}`、總句數、預估秒數與 `ok`（沒有未解決項才為 true）。純函式，不連 Edge、不寫入磁碟、不載入模型。
- `start` 在有任何未解決項時回 409，帶出未解決的行號與片段，不得先合成再失敗；預設內建句庫路徑不受影響。
- 介面（工單 08）據此顯示合成前的校對表：可改寫文字或移除該句，全部沒有未解決項後才能開始。
- 測試 0 失敗、0 跳過；路由權限測試通過。

## Comments

### 2026-11-24 實作摘要（分支 `mv2/13-text-preview`）

純函式與路由，沒有改 `web/`、`tools/tts-bench/`、`transcription.py`。校對邏輯在 `src/tts/training/sentences.py` 的 `review_text_list(raw)`（內部就是 `parse_text_list` 加 `normalize_digits`，沒有複製任何標準化邏輯）；`start` 的 Edge 文字清單路徑改走同一個函式，所以預覽顯示 `ok: true` 的清單一定被 `start` 接受。內建句庫（`preset`）路徑不經過這個檢查，不受影響。

**`POST /api/tts/training/text-preview`**（ADMIN，已登記 `ROUTE_ACCESS`）

請求：`{"sentences": "<一行一句的文字>"}`。格式與限制和 `start` 相同（`parse_text_list`：UTF-8、一行一句、去空行與重複、每句最多 500 字、最多 5000 句、至多 1 MB、不得含控制字元）。不需要 `corpus`、`name`、確認紀錄，也不看 GPU 或舞台連線；不連 Edge、不寫磁碟、不載入模型。

成功（HTTP 200）：

```json
{"code": 0, "msg": "ok", "data": {
  "ok": false,
  "total": 2,
  "unresolved_count": 1,
  "estimated_seconds": 4.2,
  "sentences": [
    {"index": 1, "text": "我有3個蘋果", "spoken": "我有三個蘋果", "unresolved": []},
    {"index": 2, "text": "價錢是$50", "spoken": "價錢是$50",
     "unresolved": [{"text": "$50", "start": 3, "end": 6, "reason": "currency"}]}
  ]}}
```

- `index` 從 1 起算，是清理後清單（空行與重複行已去掉）的位置，也就是 `start` 實際會合成的順序；`start` 的 409 用同一個 `index`。
- `spoken` 是展開後的文字；有未解決項的片段在 `spoken` 保留原文。`unresolved[].start`／`end` 指向 `text` 的字元位置，`reason` 是 `numerals.py` 的原因碼（`currency`、`degree`、`ambiguous_year` 等）。
- `unresolved_count` 是未解決片段總數；`ok` 為 `unresolved_count == 0`。`estimated_seconds` 取到小數一位，是平均語速的估計，不是量測。
- 錯誤沿用 `{"code": -1, "msg": "繁體中文原因"}`：body 不是 JSON 物件或 `sentences` 不是文字 400；清單沒有任何句子、含控制字元、單句過長、超過 5000 句 400；超過 1 MB 413。

**`POST /api/tts/training/start` 的新增 409**

Edge 語料以 `sentences` 提交且有任何未解決項時，在建立工作之前回 409（沒有工作、沒有子程序、沒有合成、語料沒有新句子）：

```json
{"code": -1,
 "msg": "有數字無法確定怎麼念，請先改寫或移除再開始：第 2 句「$50」；第 3 句「25°C」",
 "unresolved": [{"index": 2, "text": "$50", "reason": "currency"},
                {"index": 3, "text": "25°C", "reason": "degree"}]}
```

這個 409 沒有 `preflight` 欄位（與既有的前置檢查 409 區別：有 `unresolved` 的是文字問題，有 `preflight` 的是環境問題）。檢查順序：欄位與清單格式 → 未解決項 409 → 前置檢查（舞台、顯存、確認紀錄等）。

**給工單 08**：校對表由 `text-preview` 的 `sentences` 逐列顯示，管理者改寫或移除後把全部列重新以換行串成 `sentences` 再預覽，`ok` 為 true 才啟用「開始」。送出 `start` 用的就是預覽通過的同一份文字。

**驗證**：基準（`matcha-training` tip）2 failed（PDF OCR 與 role coordinator，與先前相同）、2179 passed、3 skipped；本分支 2 failed（同兩項）、2200 passed（新增 21）、3 skipped，新測試 0 失敗、0 跳過。lock check、ruff、pyright、`check-integration.py` 通過；`tests/test_route_access.py` 通過；未動 `web/`，略過網頁步驟。

**未解決**：`index` 是清理後清單的位置，不是上傳檔案的原始行號（`parse_text_list` 會丟掉空行與重複行）；校對表以 `index` 對應即可，若 08 想顯示原始行號需要另外擴充。
