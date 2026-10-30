<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 組合資料模型、轉換與各自保存
Status: ready-for-agent

依[規格](../spec.md)「組合」「成員欄位一致」「各自保存」「轉場」「天氣工具」「共用服務」。

- 角色庫改為組合結構：主數位人 id、成員清單（設定檔 id、啟用、專長介紹、交接規則、交接說明 中／英、工具；天氣工具含場域預設地點）、主數位人同樣的交接欄位、轉場（預設＋個別方向覆寫）。取代 `pair`、單一 `handoff`、頂層 `weather`。
- 自動轉換既有 `config/avatar_profiles.yaml`（version 1）：pair.main → 主數位人；pair.specialist → 第一位成員並帶入 handoff 的說明／規則／交接說明與 weather 地點；return_announcement 轉為主數位人的交接說明；既有方向轉場轉為個別覆寫；轉換可重複執行、先備份。
- 驗證：啟用的專門數位人 ≤ 5；天氣工具 ≤ 1；成員與主數位人相容（取代 `compatible_pair`）；成員不重複；主數位人不能同時是專門成員。
- 各自保存：每位成員有修訂版本，儲存單一成員只檢查該成員版本；更換主數位人、加入／移出、啟用名單變動檢查組合版本。新增或調整的路由列入 `ROUTE_ACCESS`（ADMIN，ADR 0021）。
- 只改資料層與 API；執行期（03）、路由（02）、介面（04）另票，必要的暫時相容層寫在 Comments。

## Comments
