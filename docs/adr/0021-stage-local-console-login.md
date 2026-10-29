<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

---
status: accepted
---

# 舞台僅限本機，控制台需管理者登入

2026-10-29 全專案審查發現後端沒有任何存取控制：服務監聽 `0.0.0.0`，
CORS 允許任意來源並攜帶憑證，任何區網主機或網頁都能讓舞台唸任意文字、
清除對話或讀取伺服器檔案。使用者確認部署前提：管理者從同一區網或經 VPN
連入控制台，數位人舞台只在場域主機本機開啟，只有一種管理者權限，
現場人員不使用控制台；不支援公開網際網路。

因此每條路由必屬三類之一：公開（`GET /health` 與靜態前端檔）不需憑證；
舞台（`GET /api/stage`、`GET /api/vad`、`client_role=stage` 的 `POST /offer`
與舞台附件）只接受 loopback 來源，區網請求回 403；其餘皆為管理類，
需管理者 session，本機也不例外。管理者以密碼登入取得
`HttpOnly; Secure; SameSite=Strict` session cookie，狀態變更請求另驗 `Origin`；
密碼只以 hash 存於 gitignore 的 `config/admin.env`。前端改由後端同源提供，
移除 `aiohttp_cors`。新增路由必須先歸入這三類之一。

此取捨讓舞台免登入即可在 kiosk 開機自動進入，代價是舞台能力只能從場域
主機本身取得；`Secure` cookie 也使區網連入的控制台需經 HTTPS。
細節見[規格](../../.scratch/security-hardening/spec.md)。

## 捨棄的替代方案

- **只綁 localhost**：最簡單，但管理者需從區網或 VPN 連入控制台，
  且本機任何程序與瀏覽器分頁仍可不經驗證呼叫管理類路由。
- **Bearer token**：token 必須存在前端可讀的儲存空間，一次 XSS 即可外洩；
  還要另外處理發放與輪替。`HttpOnly` cookie 讓腳本讀不到憑證。
- **mTLS**：每台管理裝置都要安裝並更新用戶端憑證，場域部署與瀏覽器操作
  成本過高；單一管理者權限下，密碼登入已足夠。
