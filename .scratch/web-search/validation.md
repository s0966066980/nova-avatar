<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 網頁搜尋驗證

最新狀態：已修復相容請求，中英文實網搜尋與本機模型回合成功；見[修復驗證](repair-validation.md)。下方保留初次驗證與修復前紀錄。

日期：2026-11-03。未變更目前角色的啟用設定，功能預設關閉。

## 本機與實網

- 以獨立 loopback 埠 18080 暫時載入現有 Gemma 4 E2B GGUF，測完關閉本次持有的 llama-server；未替換正式執行服務。
- 改善指令後八個合成案例的搜尋／不搜尋與重用判斷符合預期：寒暄、光合作用、附件摘要、中英文最新資訊、同主題追問、明確重新查詢、不同城市換題。規劃時間約 0.11–0.43 秒；只代表此組案例，不代表任意問題的判斷正確率。
- 原始合成案例與結果見 [live-validation.json](live-validation.json)。內容不含訪客資料或金鑰。
- 經 PublicResolver 與受限讀頁流程讀取 `https://www.python.org/downloads/` 成功，產生 8,000 字元的頁面摘錄。
- 真實 DDGS DuckDuckGo／Brave 在此主機測試時均未提供可用結果。DuckDuckGo 曾回傳 HTTP 202 驗證頁；不能宣稱實網搜尋成功。已驗證服務將此情況回報為 unavailable，不製造最新資訊依據。
- 搜尋成功、來源展示與回答接入另以確定性的外部結果 fixture 驗證；再以真實 Gemma 模型跑過 VoiceTurnSession，合成新舊票價來源得到新票價回答及正確來源事件，約 0.79 秒（不含真實搜尋與影音播放）。見 [local-turn-validation.json](local-turn-validation.json)。
- 正式建置的舞台經 Chrome 驗證搜尋狀態、展開來源、取消清除、桌面與 390px 手機寬度，無瀏覽器錯誤；見 [桌面畫面](stage-desktop.png) 與 [手機畫面](stage-mobile.png)。WebRTC 與搜尋結果使用 fixture。
- 未完成真實 WebRTC 含影音的搜尋回合，尚無此功能的感知首音延遲實測。

## 自動驗證

涵蓋角色政策保存與快照、搜尋前等待路由、原始問題與附件／RAG 隔離、DDGS 限定引擎與備援、五筆／三頁限制、共用截止時間、DNS 公開位址檢查、受限重新導向、部分失敗、追問重用與清除、插話取消後不交付舊結果，以及來源連結安全與前端輪次隔離。完整 CI 對應檢查：`uv lock --check`、Ruff、Pyright、品牌／授權與離線整合稽核均通過；Python 全套 1493 passed、3 skipped。前端 `npm ci` 已完成，production dependency audit 為零漏洞；lint、260 項前端測試與正式建置均通過。沿用本機既有開發環境，未重建正式 Python venv 或替換 GPU 套件。

## 再次實測

使用者要求的再次實測見 [retest.md](retest.md)。DDGS 整合搜尋仍未成功；DuckDuckGo 的直接 HTTP 對照可取得 10 筆結果，Brave 回 429。這縮小了待排查範圍，尚未視為修復。
