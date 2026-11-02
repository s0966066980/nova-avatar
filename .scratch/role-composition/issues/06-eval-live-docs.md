<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 路由評估、實機驗證與文件
Status: resolved
Blocked by: 01, 02, 03, 04, 05

orchestrator 執行：以 02 擴充的題組量 E2B 路由正確率；實機建立至少三位成員的組合（可用既有設定檔複製）測試任意直接交接（含客服 → 天氣）、追問留在原角色、返回主數位人、轉場覆寫；記錄顯存。更新 README、`docs/project-status.md`、ADR 0016 的後續註記。

## Comments

### 2026-11-02 實機結果（orchestrator，`role-composition` @ 67f52e9）

**組合**：現場 `config/avatar_profiles.yaml` 啟動時自動轉成 v2（備份 `avatar_profiles.yaml.v1-20261102T132547.bak`）。主數位人 main（`musetalk_angela`）＋天氣助手（`musetalk_1`）＋兩位測試成員 `rc06_service`「客服小幫手（測試）」（複製 main，`musetalk_angela`）、`rc06_traffic`「交通導覽（測試）」（`musetalk_1`）；覆寫 `rc06_service → weather` slide_left 0.8 s，其餘預設 fade 0.6 s。

**直接交接**（舞台，Edge TTS 合成麥克風語音經 ASR；`validation/live-handoffs-2026-11-02.json`）：main 留在 main → 天氣（main→weather）→ 追問「那後天呢」留在天氣 → 訂單（weather→rc06_service，**直接**）→ 退貨追問留在客服 → 天氣（rc06_service→weather，用覆寫 0.8 s）→ 捷運（weather→rc06_traffic）→ 公司介紹（rc06_traffic→main）。8/8 符合預期，每次播的都是目的角色自己的交接說明。第 9 題「我想問明天的天氣，也想查我的訂單」被 ASR／VAD 在逗號停頓處切成「我想問明天的天氣」，交給天氣是對的，不計入；混合主題改由文字題組驗證。

**E2B 路由正確率**（`routing-eval/e2b-2026-11-02.{json,md}`）：27/30，路由 P50 0.24 s。需交接 8/8、成員間直接交接 12/12、延續追問 5/5、**混合主題 2/5**——n26–n28 都直接交給句中第一個主題的角色而沒有 clarify。交接試算（`explain=True`）直打 E2B 也重現（「明天會下雨嗎？另外我想退貨」→ 客服）。建議另開一票處理（例如在路由前以句中命中多位成員的關鍵字判斷混合主題，或調整提示），需使用者決定。

**資源**：後端未啟動 436 MiB → 啟動並套用三位成員後 14 300 MiB（含 MuseTalk TensorRT、faster-whisper small、E2B llama-server）。log 顯示啟動讀一份素材（main）、套用時只再讀 `musetalk_1` 一份：同素材成員共用快取，與 03 的估算一致（每位成員顯存只多 latents 數 MiB）。後端主程序 RSS 4.4 GiB。

**交接試算**：路由需管理者登入，未從 HTTP 測；以相同的 `route_question(..., explain=True)` 對現場組合與 E2B 試 5 題，0.36–0.50 s，原因可讀。

**文件**：README 角色設定段改寫為一主多專、任意直接交接、交接試算與轉場覆寫；`docs/project-status.md` 新增「角色組合」能力列與「角色組合實機驗證」；ADR 0016 加註由 ADR 0023 取代兩角色前提。

### 需要使用者確認

1. 在控制台新版「角色組合與交接」頁看兩位測試成員、試算幾題；用兩個控制台同時編輯同一位成員，確認衝突只出現在該成員；換主數位人時出現停用不相容成員的確認。
2. 舞台按「返回主數位人」、閒置重置後回到主數位人，閒置招呼只由主數位人播出（需要管理者登入／等待閒置，未自動化）。
3. 混合主題 2/5 是否另開票改善。
4. 確認後移除測試成員 `rc06_service`、`rc06_traffic`（可在新版頁面「移出」並在數位人設定檔刪除，順便驗證介面）。

### 2026-11-02 使用者確認

使用者確認控制台與舞台的人工檢查都沒問題。測試成員 `rc06_service`、`rc06_traffic` 已移出組合並刪除設定檔，組合回到主數位人＋天氣助手。`role-composition` 已合併進 `main`（ba3f691），`main` 上 CI 全部通過（pytest 1465 passed、3 skipped；web 257 passed）。混合主題 2/5 尚未決定是否另開票。
