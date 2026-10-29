<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 前端由後端同源提供與 kiosk
Status: resolved
Blocked by: 03

依[規格](../spec.md)「信任邊界」。啟動腳本以 Vite dev server 在 `0.0.0.0:3000` 提供正式環境（`scripts/start-all.sh:201`、`start-frontend.sh:188`、`start-kiosk.sh:29`；`web/vite.config.js:17,30`），整個 `web/`（含 `web/logs/*.log`）對區網公開；後端在 `web/dist` 缺 `index.html` 時改提供整個 `web/`（`src/server/server.py:151-152`）。

- 啟動腳本先 `npm run build`，控制台與 kiosk 都開後端 `https://localhost:8010`（kiosk：`/stage.html?kiosk=1`）。確認 Vite build 會輸出 `stage.html`。
- `npm run dev` 預設綁 `127.0.0.1`，僅供開發。
- 後端：`web/dist` 不存在即啟動失敗並提示建置，不再退回 `web/`。刪除並 gitignore `web/logs/`。
- kiosk：移除 `--use-fake-ui-for-media-stream`（`start-kiosk.sh:59-61`），改以 kiosk 專用 profile 的 Chrome policy `AudioCaptureAllowedUrls` 只放行 `https://localhost:8010`；檢視 `--allow-insecure-localhost` 是否仍需要。
- 設定檔路徑：Vite 讀 `config/<basename>` 而後端用傳入路徑（`start-frontend.sh:181-184`、`start-all.sh:198-199`）；改傳絕對路徑。`start-backend.sh:65,79` 在 `cd` 前檢查相對路徑，一併修正。
- 更新 `tests/test_kiosk_launcher.py`、`tests/test_startup_scripts.py` 與 README。

完成：腳本測試綠；完整 CI 通過。

## Comments

### 2026-10-29 實作結果

- 後端：`create_app(frontend_dir=)` 只提供 `web/dist`（`server.FRONTEND_DIST`，以專案根目錄定位，不受工作目錄影響）；缺 `index.html` 即拋 `FrontendNotBuilt` 並提示 `npm run build`，不再退回 `web/`。`app.py` 在載入模型前先檢查，快速失敗。新增 `GET /` 回控制台頁，歸入 `ROUTE_ACCESS` 公開類。
- `start-all.sh`：先 `npm run build`，再啟後端並等待它結束（後端結束碼即腳本結束碼）；不再開 Vite、不清 3000 埠。只印控制台 Local／Network（8010）與舞台 Local；舞台 Network 網址移除（#03 留下的項目）；HTTP 模式提示區網登入需 SSL。
- `start-frontend.sh`：預設建置 `web/dist`；`--dev` 才啟 Vite 開發伺服器。`vite.config.js` 預設綁 `127.0.0.1`，各設定檔 `app.web.host` 改 `127.0.0.1`；#03 的 proxy `changeOrigin: false`、`xfwd: true` 保留。
- 設定檔路徑：三支腳本以 `realpath -m` 將參數（相對於呼叫者目錄）轉為絕對路徑，Vite 與後端讀同一檔案；`start-backend.sh` 的 `.venv` 檢查改用專案根目錄。
- kiosk：改開 `https://localhost:8010/stage.html?kiosk=1`，移除 `--use-fake-ui-for-media-stream`。Linux 上 Chrome policy（`AudioCaptureAllowedUrls`）只能放在 `/etc` 且全機生效、需 root，故改在 kiosk 專用 profile 的 `Default/Preferences` 寫入：舞台來源麥克風允許、其他來源封鎖，保留其他偏好。已用 Chrome 156 headless 驗證：舞台來源 `granted`、其他來源 `denied`。
- `--allow-insecure-localhost`：預設自簽 localhost 憑證仍需要（Chrome 156 驗證無此旗標無法載入）；只在 https 時加入。`--ignore-certificate-errors-spki-list` 範圍更窄但可能觸發「不支援的旗標」資訊列，未採用。
- `web/logs/` 從未納入版本控制，已由 `.gitignore` 的 `logs/` 排除，且後端不再提供 `web/` 原始樹；主工作目錄的 `web/logs/*.log`（上游舊日誌）需使用者自行刪除。
- 測試：新增 `tests/test_frontend_serving.py`；更新 `test_kiosk_launcher.py`、`test_startup_scripts.py`（含 start-backend／start-frontend）、`web/tests/page-routing.test.js`；`tests/access_helpers.py::built_frontend()` 提供測試用建置目錄。README、`docs/installation.md` 已更新。
- 驗證：ruff、check-integration、web lint/test(199)/build 通過；pytest 844 passed、3 skipped（另 2 項 worktree 環境既有失敗已排除）。
- 合併 `security-hardening`（含 #06、#11、#17）後：解決 `docs/installation.md` 衝突，`setup-env.sh` 下一步改為先建置再開 8010；pytest 880 passed、3 skipped，web test 202 通過，lint/build/ruff/check-integration 通過。
