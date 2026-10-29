<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 舞台連線韌性與 lint
Status: ready-for-agent

依[規格](../spec.md)。`web/stage.html`（公開 kiosk，約 1100 行 inline JS）不在 ESLint 範圍內。

- fetch（`:721,736,946`，`startSession` `:1064`）皆無逾時；啟動時按鈕被隱藏（`:896,1067`）→ 後端接受連線後卡住時永遠停在「連線中」。全部加 `AbortController` 逾時；超過 N 秒一定顯示重試並自動重連。
- data channel（`:917`）無 `onclose`／`onerror`：通道關閉而影像仍在時字幕、看板停止。比照 `web/src/useWebRTC.js:155-160` 處理並重連。
- 若可行，把 inline script 抽成 `web/src/stage/*.js` 模組以便 `node --test`；否則以 `eslint-plugin-html` 讓 `npm run lint` 涵蓋 `stage.html`。
- 守門：`npm run lint` 涵蓋舞台腳本。

完成：逾時與重連邏輯的測試；`npm run lint`、`npm test`、`npm run build` 通過。

## Comments
