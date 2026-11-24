<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 訓練工作台介面
Status: ready-for-agent
Blocked by: 05, 06

依[規格](../spec.md)與 07 確認後的原型。在控制台實作訓練工作台，串接 05、06 的路由；補齊三份 locales；前端測試 0 失敗、0 跳過；`npm run lint`、`npm run build` 通過。不得為了介面方便而放寬任何路由的權限分類。

## 已確認的設計決定（2026-11-24）

依 `prototype/design.md`，管理者確認了規格第 12–17 點：入口在設定新分類「聲線訓練」；Edge 條文在選來源時確認；內建句庫免校對；第一版沒有下載路由；少量語料只提醒；舞台連線只顯示原因；完成畫面只有三句預設試聽。原型中的 50 MB、40 字、40–60 分鐘為示意值，以工單 05、06 的實際值為準。
