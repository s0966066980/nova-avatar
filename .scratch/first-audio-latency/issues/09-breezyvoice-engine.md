<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# BreezyVoice 引擎
Status: ready-for-agent

依[規格](../spec.md)。BreezyVoice（MediaTek，程式碼與權重 Apache-2.0）以 CosyVoice v1 為基礎，吃繁體字、以 g2pW 處理台灣讀音、可指定注音；不支援串流，以參考音訊＋逐字稿複製聲線。

- 先試以專案現有 `scripts/cosyvoice_fastapi_server.py` 載入 BreezyVoice 權重；不相容再新增獨立伺服器，同樣只綁 loopback、模型目錄來自 `models/` 掃描（ADR 0021、CODING_STANDARDS 規則 1）。
- 新增 `breezyvoice` 引擎：參考音訊與逐字稿取自音訊庫；以可播回覆片段為單位合成。
- 權重下載比照 `scripts/musetalk_weights.py` 釘 commit 與 sha256。
- 範例參考錄音只供開發，不設為正式預設；在 Comments 記錄其授權查證結果。
- THIRD_PARTY_NOTICES 與軟體組合文件加入 BreezyVoice。

完成：引擎單元測試；實機合成一句繁體中文並記錄第一個片段合成時間。

## Comments
