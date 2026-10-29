<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# Coding Standards

審查變更時逐條套用；每條都要對 diff 判定「符合」或「違反」，違反時指出
檔案與行號。可機械檢查的規則交給 `.github/workflows/ci.yml` 的 lint 與測試。

1. **請求欄位只指名伺服器管理的項目。** 代表路徑、目錄或 URL 的欄位只接受
   伺服器管理清單中的 ID（參考音訊庫、`models/` 掃描結果、設定檔定義的
   LLM 端點），由伺服器把 ID 解析成實際位置。原因：使用者字串直接當路徑
   或 URL 會外洩任意檔案或打到任意主機（SSRF）。
2. **跨執行緒回到 session 一律經 `loop.call_soon_threadsafe`。** TTS、渲染等
   其他執行緒要觸及 session 或 asyncio 物件時，排程到 session 的 event loop；
   loop 已關閉或不存在時捨棄這次回呼並記錄，讓它隨 session 結束。原因：
   在錯誤執行緒直接執行會破壞 session 狀態，且難以重現。
3. **async handler 的重工作進 `asyncio.to_thread`。** 可能超過約 50 ms 的工作
   （解碼、模型載入、ffmpeg、檔案 IO）在 worker 執行緒執行。原因：卡住
   event loop 會凍結所有連線，包括舞台的收音與影音。
4. **覆寫或刪除使用者資產前先查使用中狀態，並移入回收桶。** 頭像、背景、
   參考音訊等資產若正被設定檔或進行中的對話使用則拒絕；可刪除者移到
   `.deleted` 回收桶（參考 `src/scene/service.py` 的背景刪除），而非直接抹除。
   原因：誤刪會讓舞台在場域中斷且無法復原。
5. **名稱含 `sanitize` 的函式真的跳脫 HTML。** 它的輸出可安全插入 DOM；只做
   其他清理（例如移除語音標記）的函式改用描述實際行為的名稱。原因：
   呼叫端會因名稱而把輸出當作安全 HTML，形成 XSS。
