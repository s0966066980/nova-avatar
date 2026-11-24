<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# Edge 文字清單：合成前校對
Status: ready-for-agent

依[規格](../spec.md)第 7、13 點與介面原型。工單 06 的 `POST /api/tts/training/start` 直接收 `sentences`，數字展開後有未解決項的句子會等到合成後才進入「待確認」，管理者白白花了 Edge 請求才發現。決定 13 要求：Edge 的上傳文字檔要在**合成前**校對（內建句庫免校對）。

- 新增 `POST /api/tts/training/text-preview`（ADMIN，登記 `ROUTE_ACCESS`），body `{sentences: string}`（與 start 相同的格式與限制，沿用 `parse_text_list`），回傳逐句 `{index, text, spoken, unresolved: [...]}`、總句數、預估秒數與 `ok`（沒有未解決項才為 true）。純函式，不連 Edge、不寫入磁碟、不載入模型。
- `start` 在有任何未解決項時回 409，帶出未解決的行號與片段，不得先合成再失敗；預設內建句庫路徑不受影響。
- 介面（工單 08）據此顯示合成前的校對表：可改寫文字或移除該句，全部沒有未解決項後才能開始。
- 測試 0 失敗、0 跳過；路由權限測試通過。
