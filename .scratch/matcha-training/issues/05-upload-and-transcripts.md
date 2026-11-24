<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 上傳錄音與逐字稿
Status: ready-for-agent
Blocked by: 03

依[規格](../spec.md)第 5、6、7 點。

- 上傳音檔與來源宣告：選「自己錄的」或「有書面授權」要有聲明，選「開發用」只能產出 Development only。檢查大小、格式；轉成 16 kHz 單聲道並做 `audio_qc` 檢查。
- 逐字稿：上傳同檔名的 `.txt` 或 `metadata.csv`（`檔名|文字`）；沒有逐字稿時用 faster-whisper 產生並轉成繁體中文，使用已快取的模型，在工作中載入、完成後釋放。
- 校對 API：逐句修改、排除、確認；數字展開後的文字一併回傳；全部確認前不得標示為可訓練。
- 新路由全部登記 `ROUTE_ACCESS` 為 ADMIN（ADR 0021）。

## 範圍補充（2026-11-24）

- 新路由集中放在新檔 `src/server/routes/tts_corpus.py`，只在 `routes/__init__.py`、`server.py`、`access.py` 加註冊與權限列，避免與 06（`routes/tts_training.py`）衝突。
- 使用 `src/tts/training/` 的語料 API（工單 03 Comments），不要另建儲存格式；音檔解碼與品質檢查在這張工單做。
- 自動逐字稿以背景執行緒進行，請求不得阻塞事件迴圈（CODING_STANDARDS）。
