<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 前端由後端同源提供與 kiosk
Status: ready-for-agent
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
