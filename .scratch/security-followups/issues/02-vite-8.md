<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 升級 Vite 8 清除剩餘 npm audit
Status: ready-for-agent

`npm audit --omit=dev` 仍有 vite（high）與 esbuild（moderate）兩項，只能以 Vite 8 破壞性升級修正。正式環境已改由後端提供 `web/dist`，dev server 只綁 127.0.0.1，風險限於開發機。

升級 `vite`、`@vitejs/plugin-vue` 並調整 `web/vite.config.js`（多頁輸入含 `stage.html`、代理 `changeOrigin: false, xfwd: true`）。完成：`npm audit --omit=dev` 為 0、lint／test／build 通過、`tests/test_frontend_serving.py` 通過。

## Comments
