<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 安全強化與場域穩定性

Status: resolved

2026-10-29 全專案審查發現：後端無存取控制、可外洩任意檔案、控制台 XSS、
多個卡死 event loop 與讓 kiosk 失聰的路徑，且既有 CI（ruff、pytest、ESLint）
一項都沒抓到。使用者已確認以下範圍並要求實作。

## 已確認的部署前提

- **管理者**從同一區網或經 VPN 連入**控制台**；不支援公開網際網路。
- **數位人舞台**只在場域主機本機開啟。
- 只有一種管理者權限；**現場人員**不使用控制台。

## 信任邊界

路由分三類，每條路由必屬其一：

| 類別 | 路由 | 規則 |
|---|---|---|
| 公開 | `GET /health`、靜態前端檔 | 不需憑證；`/health` 只回就緒狀態 |
| 舞台 | `GET /api/stage`、`GET /api/vad`、`client_role=stage` 的 `POST /offer`、舞台附件 | 只接受 loopback 來源；區網送來的回 403 |
| 管理 | 其餘全部 | 需管理者 session；本機也不例外 |

管理者以密碼登入，取得 `HttpOnly; Secure; SameSite=Strict` session cookie；
狀態變更請求另驗 `Origin`。密碼只存 hash 於 gitignore 的 `config/admin.env`。
移除 `aiohttp_cors`：前端改由後端同源提供後不再需要 CORS。

## 輸入限制原則

- 代表檔案路徑、目錄或 URL 的請求欄位只接受伺服器管理清單中的 ID
  （參考音訊庫、`models/` 掃描結果、設定檔定義的 LLM 端點）。
- 上傳在落地前驗證，串流累計位元組並設上限，失敗路徑清除暫存。
- 解碼前先讀標頭檢查尺寸／時長；重工作進 `asyncio.to_thread`。

## 驗收

- 每張 issue 以 `tdd` 實作：先有失敗的回歸測試，再修正。
- 完整驗證通過：`.github/workflows/ci.yml` 中的所有步驟。
- 新增的自動檢查（路由契約測試、`vue/no-v-html`、ruff `S`/`ASYNC` 子集、
  pyright `reportPossiblyUnbound`、`stage.html` lint）在合併時為綠燈。
- 依 AGENTS.md 保留歸屬聲明；新檔案使用 Nova Avatar SPDX 標頭。

## Issue 圖

```
01 依賴鎖定 ─┐
02 信任邊界文件
03 存取控制 ──┬─ 04 參考音訊庫 ─────────┐
              ├─ 06 匯入覆寫 ─ 08 安全載入 ┤
              ├─ 07 LLM 端點白名單 ──────┼─ 10 ruff 安全規則
              ├─ 09 不阻塞 event loop ───┘
              └─ 15 前端同源與 kiosk ─ 16 啟動腳本程序管理
05 Markdown 淨化
11 執行緒安全 ─ 12 回合收尾 ─ 13 渲染停止與 pyright
14 舞台韌性
17 固定版本與離線資源
```
