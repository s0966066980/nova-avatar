<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->

# 網頁搜尋修復驗證

日期：2026-11-03。使用者確認修復方案後實作；角色搜尋啟用設定維持原值。

## 真實搜尋與讀頁

原始失敗命令：`PYTHONPATH=. uv run --no-sync python .scratch/web-search/diagnosis/reproduce.py`。
修復前 `unavailable sources=0`、assertion failed；修復後 `available sources=5`，來源含已讀取網頁，assertions 通過。

| 查詢 | 狀態 | 來源 | 搜尋與讀頁時間 |
| --- | --- | --- | --- |
| Python official downloads | available | 5 筆，3 頁已讀 | 0.906 秒 |
| 台北 最新 展覽 活動 | available | 5 筆，3 頁已讀 | 2.782 秒 |
| 中央氣象署 官網 | available | 5 筆，3 頁已讀 | 0.713 秒 |

直接測試 Brave 仍回 `rate_limited`，未為了成功增加重試或換用其他未核准引擎。以上僅表示此次網路條件下的成功，搜尋引擎未來仍可能限流或驗證。

原始事件及結果見 [repair-live.json](repair-live.json)。

## 真實本機模型回合

以臨時空閒 loopback 埠啟動現有 Gemma 4 E2B，透過 VoiceTurnSession 使用真正 planner、搜尋、讀頁與回答，沒有 mock 搜尋結果，測完停止本次持有的模型服務。

- 寒暄正常回答且不搜尋。
- 中文最新展覽及英文 Python 問題均取得來源事件，來源區分已讀頁面與搜尋摘要。
- 另以「中央氣象署官方網站用途」及「最新 Python 完整版本號、只口述」兩題驗證來源與回答串接，取得內容回答且無 pipeline error。後者把測試 token 預算由 512 提高至 1024、字數上限設 300；原來 512 預算的英文測試只產生不完整的口語摘要，不能視為任意設定下的回答品質保證。
- 這兩題從接受問題到取得文字回答各約 2.62、2.13 秒；使用測試 avatar，不含真實 WebRTC、TTS 或嘴型播放，並非感知首音延遲。

結果見 [repair-turns.json](repair-turns.json)。

## 回歸與檢查

新增回歸先在原實作出現 DDGSException，再於相容層實作後通過。測試經真實 DDGS 的 engine request／parser，僅以 HTTP 回應 fixture 取代外部網路，未 mock 最終搜尋 hits。涵蓋實例標頭不污染全域、相容請求內容、HTTP 202／429／500、合法空結果、核准引擎及版本檢查，並沿用既有輪次取消、預算及 SSRF 測試。

搜尋相關 33 項測試通過。完整 CI 對應檢查：`uv lock --check`、Ruff、Pyright、品牌／授權與離線整合稽核均通過；Python 全套 **1499 passed、3 skipped**。前端完成 `npm ci`、production dependency audit（零漏洞）、lint、**260 項測試**與正式建置。沿用本機既有 Python 開發環境，未重建正式 venv 或替換 GPU 套件。

本次僅新增專案自己的相容層、回歸與文件，沒有修改第三方套件檔案、全域引擎標頭或角色啟用設定；測試模型服務已關閉。
