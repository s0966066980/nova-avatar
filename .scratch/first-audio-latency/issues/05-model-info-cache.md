<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 模型資訊查詢移出每輪路徑
Status: resolved

依[規格](../spec.md)。`src/llm/context_usage.py:68-88`（10/29 新增）每輪先呼叫 llama-server 的 `/props`、`/apply-template`、`/tokenize`，約 0.2–0.4 s，計入「LLM 初始化時間」。

- `/props` 於模型載入或切換時取一次並快取。
- Context 用量改為回覆完成後非同步計算，或以本地估算取代每輪 tokenize，不阻塞主回答。
- 路由每次新建 OpenAI client、RAG 每次新建 aiohttp session：改為重用。

完成：主回答開始前不再有這三支呼叫的回歸測試；Context 用量顯示仍正確。

## Comments

### 2026-10-30 實作結果（分支 `fal/05-model-info-cache`）

- `/props`：`ensure_server` 每次載入或切換模型後以 `deployed_capacity(refresh=True)` 取一次並快取；
  重新取得失敗時清除舊值，不沿用前一個模型的容量。主回答只讀快取（`cached_capacity`），
  未命中時於背景執行緒補取，回覆結束時再讀一次。
- Context 用量：主回答前改為本地估算（標示 `estimate`），不再呼叫 `/apply-template`、`/tokenize`；
  回覆串流結束時以 provider usage（`include_usage`）更新為實際值。超容量改由 llama-server 回報：
  `exceed_context_size_error`（llama.cpp b10505 原始碼確認，HTTP 400）對應 `ContextCapacityError`，
  既有記憶不變。原本以 tokenizer 預檢拒絕的分支已移除。
- 路由：`RoutingClients` 依端點重用同一 OpenAI client（加鎖、可多執行緒同時呼叫），
  `RoleCoordinator.close()` 於關機時關閉，之後的路由請求拒絕。
- RAG：同一 event loop 共用一個 aiohttp session（金鑰與逾時逐請求設定，可同時檢索），
  `on_shutdown` 在語音工作階段關閉後呼叫 `close_shared_session()`。
- 回歸測試：主回答前零次模型資訊請求且用量正確、伺服器回報超容量不動記憶、切換模型更新容量、
  路由並行重用單一 client 並於關機關閉、RAG 連線重用（含並行）並於關機釋放。
- 驗證：ruff、pyright、`scripts/check-integration.py` 通過；pytest 1087 passed，失敗僅兩個已知
  worktree 基準失敗，另 `test_server_shutdown` 在全套負載下偶發逾時一次（該測試使用自己的
  shutdown hook，與本變更無關，單獨重跑 10 次皆通過）。
- 無需實機驗證；省下的初始化時間由 issue 01 的量測工具於最終驗收一併量測。
