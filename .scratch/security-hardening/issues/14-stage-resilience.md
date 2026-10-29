<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 舞台連線韌性與 lint
Status: resolved

依[規格](../spec.md)。`web/stage.html`（公開 kiosk，約 1100 行 inline JS）不在 ESLint 範圍內。

- fetch（`:721,736,946`，`startSession` `:1064`）皆無逾時；啟動時按鈕被隱藏（`:896,1067`）→ 後端接受連線後卡住時永遠停在「連線中」。全部加 `AbortController` 逾時；超過 N 秒一定顯示重試並自動重連。
- data channel（`:917`）無 `onclose`／`onerror`：通道關閉而影像仍在時字幕、看板停止。比照 `web/src/useWebRTC.js:155-160` 處理並重連。
- 若可行，把 inline script 抽成 `web/src/stage/*.js` 模組以便 `node --test`；否則以 `eslint-plugin-html` 讓 `npm run lint` 涵蓋 `stage.html`。
- 守門：`npm run lint` 涵蓋舞台腳本。

完成：逾時與重連邏輯的測試；`npm run lint`、`npm test`、`npm run build` 通過。

## Comments

### 2026-10-29 實作結果
- 新增 `web/src/stageConnection.js`：`fetchJsonWithTimeout` 以 `AbortController` 加上與回應內容讀取共用的逾時（並以 `Promise.race` 保證上限）；輪詢 4 秒、`/offer` 15 秒、整體連線看門狗 25 秒。
- `stage.html`：三處 fetch 全改用逾時包裝；`connect()` 啟動看門狗，卡在「連線中」逾時即拆掉本次嘗試、露出重試按鈕並依退避自動重連（kiosk 與一般舞台皆是）；每次 connect/teardown 換編號，逾時後才回來的舊嘗試（如麥克風授權）會釋放音軌、不送 offer。
- data channel 補 `onclose`／`onerror`：停用互動並自動重連；同一連線的 peer 失敗與通道關閉只處理一次，不重複拉長退避。一般舞台 peer 失敗仍維持手動「重新連線」（既有測試的行為）。
- 未把 inline script 整段抽成模組（多個既有測試以正規式讀取 stage.html）；改以 `eslint-plugin-html@8.2.1`（devDependency，固定版本）讓 `npm run lint` 涵蓋 `stage.html`，順手修掉兩個空 catch。舞台 vm 測試 harness 移到 `web/tests/helpers/stageHarness.js` 共用。
- 測試：`web/tests/stage-connection.test.js`、`web/tests/stage-resilience.test.js`；`npm run lint`／`npm test`（合併後 193 通過）／`npm run build`、ruff、check-integration 通過。pytest 798 通過，2 個失敗為 worktree 缺模型權重／OCR 環境所致，與本票無關。
