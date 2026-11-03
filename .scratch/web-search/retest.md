<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->

# 網頁搜尋再次實測

2026-11-03，使用真實網路、本機 Gemma 4 E2B 與 VoiceTurnSession；搜尋結果未使用 mock。未修改角色啟用設定。臨時模型服務使用當次挑選的空閒 loopback 埠，測完已關閉。

| 項目 | 結果 |
| --- | --- |
| DDGS DuckDuckGo | DDGSException: No results found |
| DDGS Brave | DDGSException: No results found |
| 整合搜尋三題 | 英文 Python 官網、台北展覽、中央氣象署均 unavailable／零來源，約 0.38–0.53 秒 |
| 公開網頁讀取 | Python 官方下載頁讀取成功，8,000 字元摘錄，約 0.20 秒 |
| 本機一般對話 | 「你好」正常回答，沒有搜尋事件 |
| 本機模型＋真實搜尋 | 中文最新展覽、英文最新 Python 都實際產生搜尋事件，再正確回答未能查證；沒有 pipeline error |
| 搜尋回歸測試 | 27 passed |
| 前端搜尋測試 | 3 passed |

## HTTP 對照

Brave 直接 HTTP 請求回 429，內容有 captcha／too many requests 標記。DuckDuckGo 直接 HTTP 請求回 200，頁面可解析出 10 個搜尋結果連結；HTTP/1 與開啟 HTTP/2 的對照皆取得相同數量。

因此不能說主機完全無法上網，或 DuckDuckGo 完全不可用；目前是 DDGS 整合路徑取不到結果，須進一步比較套件的請求參數、標頭與解析。尚未鎖定 DuckDuckGo 的唯一根因，也未修改搜尋程式或宣稱已修復。Brave 此次可確認遭限流。

完整合成測試輸入、來源事件、回答與 HTTP 診斷見 [retest.json](retest.json)。本次 VoiceTurnSession 使用測試 avatar，不含真實 WebRTC、嘴型或語音播放，時間不是感知首音延遲。
