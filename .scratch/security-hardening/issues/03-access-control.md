<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 控制台登入與路由存取控制
Status: ready-for-agent

依[規格](../spec.md)「信任邊界」。現況：無驗證、監聽 `0.0.0.0`、`aiohttp_cors` 設 `"*"` 且 allow_credentials（`src/server/server.py:154-164`）；`GET /api/conversations` 列出 sessionid，任何區網主機或網頁都能讓舞台唸任意文字、清對話、搶 stage 名額。aiohttp `request.json()` 不檢查 Content-Type，multipart 是 simple request，所以只收緊 CORS 不夠。

- 新模組（例如 `src/server/access.py`）：路由分類表與 `access_guard` middleware；舞台類只收 loopback（`request.remote`）；管理類需有效 session。
- `POST /api/login`、`POST /api/logout`、`GET /api/session`；密碼 hash（標準庫 `hashlib.scrypt`）放 `config/admin.env`（加入 `.gitignore`）；新增 `scripts/configure-admin.py` 以 getpass 設定，檔案權限 0600。登入失敗逐次延遲。
- Session cookie：`HttpOnly; Secure; SameSite=Strict`；狀態變更請求驗證 `Origin` 與 Host 一致。
- 移除 `aiohttp_cors`（程式與依賴）。
- 控制台（`web/src`）：未登入顯示登入畫面；401 時回到登入。舞台（`web/stage.html`）不受影響。
- 未設定管理者密碼時，管理類一律 503 並記錄如何執行設定腳本。
- 守門：`tests/test_route_access.py` 遍歷 `create_app()` 的所有路由，斷言每條都在分類表內，並驗證未登入 401、區網舞台 403、跨 Origin 403。
- 更新受影響的既有測試與 README 啟動說明。

完成：上述測試綠；完整 CI 步驟通過。

## Comments
