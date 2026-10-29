<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 控制台登入與路由存取控制
Status: resolved

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

### 2026-10-29 實作結果

- 分類表 `ROUTE_ACCESS`（`src/server/access.py`）以 `(method, canonical path)` 為鍵，新增路由只需加一行；`access_guard` 為 `create_app()` 第一個 middleware，未分類路由以管理類處理。
- 舞台與控制台共用的路由用 resolver 判定：`POST /offer` 依 `client_role`；附件、`/interaction`、`/human`、`/interrupt_talk` 依目標 session 是否為舞台（JSON body 上限 256 KiB）。舞台類：loopback 或已登入管理者；其餘 403。
- 密碼 hash 在 `src/server/admin_password.py`（純標準庫 scrypt），`scripts/configure-admin.py` 寫入 `config/admin.env`（0600、已 gitignore）；換密碼即登出所有 session。登入失敗依來源逐次加倍延遲（0.5 s 起、上限 30 s），同來源嘗試序列化。
- 狀態變更請求驗證 `Origin` 與 Host 同源（無 Origin 時看 `Sec-Fetch-Site`）。移除 `aiohttp_cors` 與依賴。
- 過渡期（#15 前）Vite proxy 改 `changeOrigin: false`、`xfwd: true`；後端只在 TCP 來源為 loopback 時採信 `X-Forwarded-For` 最後一跳，避免區網經 Vite 被當成本機。
- 控制台：`ConsoleRoot.vue` 依 `/api/session` 顯示 `AdminLogin.vue` 或主畫面；`installSessionExpiry()` 包裝 `fetch`，任何 401 回登入畫面；頂列新增登出鈕。`stage.html` 未變。
- 測試：`tests/test_route_access.py`（25 項含參數化）；共用 `tests/access_helpers.py::access_client(admin=, remote=, configured=)`，後續 issue 可直接取得已登入／區網／未設定的 client。前端 `web/tests/admin-session.test.js`。
- 驗證：ruff、check-integration、web lint/test(175)/build 通過；pytest 823 passed，2 failed 為 worktree 缺 `models/musetalk` 與本機 OCR 套件的既有環境問題（`test_role_coordinator`、`test_conversation_attachments` 真實 PDF），與本變更無關。
- 未處理：`start-all.sh` 仍印出舞台 Network 網址（區網開啟會 403），留給 #15 一併調整。
- 合併 `security-hardening`（含 #01 lock）後以 `uv lock --offline` 移除 lock 內的 `aiohttp-cors`；`uv lock --check` 通過。合併後 pytest 828 passed（同上 2 項環境失敗），web test 199 通過。
- 補充：舞台類也接受已登入管理者，因控制台同樣讀取 `GET /api/stage`、`GET /api/vad`；舞台 composer 用到的 `/human`、`/interrupt_talk` 依目標 session 歸類。
