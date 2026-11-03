<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->

# 網頁搜尋失敗修復：診斷與確認方案

Status: 已完成；離線回歸、原始實網重現、中英文搜尋、本機模型回合與 CI 對應檢查通過

## 修復基準

沿用 [ADR 0024](../../docs/adr/0024-bounded-web-search-before-answer.md) 已確認的產品設計：角色獨立啟用、必要查詢外送、DuckDuckGo 優先／Brave 備援、五筆結果／三頁、共用八秒預算與輪次隔離。此次目標是既有搜尋路徑在可用的搜尋服務上取得資料，不以放寬這些邊界換取成功。

## 已執行的重現

`PYTHONPATH=. uv run --no-sync python .scratch/web-search/diagnosis/reproduce.py`

初始輸出：`status=unavailable sources=0`，assertion failed。多次重跑相同；直接呼叫 DDGS DuckDuckGo 也出現 `DDGSException: No results found.`，不需要啟動模型便能重現。

## 控制變因與事實

- 同查詢、同 httpx 直接請求，只改 User-Agent：預設得到 HTTP 202 驗證頁、零結果連結；`Mozilla/5.0` 得到 HTTP 200、10 個結果連結。見 [header-comparison.json](diagnosis/header-comparison.json)。
- 固定成功標頭後，加入 DDGS 的 `b`、`l` 參數仍為 HTTP 200、10 個結果連結。因此目前不支持「參數必然導致失敗」的假說。
- 原版 DDGS 解析器可離線解析正常搜尋頁，經真實 engine.search 重播也得到 10 筆；同一 body 改為 HTTP 202／429，BaseSearchEngine.request 會捨棄 body，只讓上層看到沒有結果。
- DDGS 9.14.4 的公開建構介面沒有 headers 參數；單純傳入 `.text(headers=...)` 不能設定 HTTP 標頭。
- 已完成完整 DDGS 可逆對照：同一 DDGS instance、同一 DuckDuckGo engine、同一 HTTP client／SSL／參數／parser，僅切換該 client 的 User-Agent。原標頭 → HTTP 202、0 筆；固定標頭 → HTTP 200、5 筆；恢復原標頭 → HTTP 202、0 筆。此主機此次失敗可歸因於原標頭觸發驗證頁，不只是 httpx 與 DDGS 的相關性對照。
- Brave 先前實測 HTTP 429；不能藉重試風暴或取消等待上限掩蓋限流。

## 預定驗收

1. 先建立可離線重播 HTTP 200 搜尋頁與 202／429 回應的回歸測試，經實際搜尋 adapter 而非只 mock 最終 hits。
2. 驗證只會使用核准引擎；不得因缺少或不相容 backend 而自動 fan-out。
3. 成功結果仍經公開網址、DNS、網域政策與重新導向檢查；限制及取消不因修復失效。
4. 原始重現命令轉綠，至少含成功搜尋結果及一個已讀頁面；再測中英文查詢與真實本機模型回合。
5. 限流、驗證頁及連線失敗明確歸為服務不可用；一般零結果與成功需有可重播案例。
6. 完整執行專案 CI 對應檢查，保存真實網路驗證結果與限制。

## 已確認修復方案

保留固定版本 DDGS，增加單一、隔離的相容 adapter，僅設定每個 DuckDuckGo engine 實例的穩定 User-Agent，再交回原 DDGS 搜尋與解析流程。此版本沒有公開 headers 擴充點，需將對 `_engines_cache` 與引擎 client 的依賴集中在 adapter，並以固定版本與實際呼叫鏈回歸測試約束；若介面不相容則明確失敗，不退回自動選擇引擎。

不修改 site-packages、不做全域 monkeypatch，不複製第三方搜尋實作。維持 DuckDuckGo／Brave 與原本八秒／五筆／三頁上限；遇到真正驗證頁或限流仍視為不可用，依既定預算走備援，不新增大量重試。此處固定標頭只是讓正常搜尋請求相容，不提供驗證碼解題或繞過登入／權限的機制。

替代方案是自行維護窄版 DuckDuckGo HTML adapter：能移除對 DDGS 內部介面的依賴，但需自行承擔搜尋頁解析與變動維護。此次若優先小範圍修復，建議先採隔離相容 adapter。

完成條件：離線回歸與原 live probe 轉綠；中英文三組查詢有可用來源並完成讀頁；至少一個真實本機模型回合使用真實搜尋結果形成回答且送出來源事件；失敗／取消與完整 CI 對應檢查通過。實網結果需清楚區分搜尋成功、僅摘要及讀頁失敗，不以只有 mock 成功作交付結論。

## 實作補記：標頭與預設參數都要隔離處理

僅固定 User-Agent 的第一次實作通過離線測試，但原 live probe 仍為 `unavailable`。重做控制變因：當時完整 `q,b,l` 在標準 HTTPX 與原 DDGS 都得到 202；`q`、`q+b`、`q+l` 的對照可得到 200 與 10 個連結。不能將任一參數單獨歸為必然有問題，也不能把早先 UA 可逆對照解釋為永久保證。

相容層因而同時固定該實例標頭，並只移除空 `b` 與預設 `l=us-en`。原始 `q` 及明確的篩選／分頁參數保留；交由搜尋引擎採自身預設地域。原始重現已得到 `available`、5 筆來源並完成讀頁。離線回歸同時檢查請求形狀、真實 DDGS parser、202／429／HTTP 錯誤、合法空結果、缺少引擎與版本不相容時不自動 fan-out。

實際結果見 [修復驗證](repair-validation.md)。
