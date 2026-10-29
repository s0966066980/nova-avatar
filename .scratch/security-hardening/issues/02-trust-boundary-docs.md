<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 信任邊界 ADR、審查規則與 AGENTS.md
Status: ready-for-agent

依[規格](../spec.md)的「已確認的部署前提」與「信任邊界」。

- 新增 `docs/adr/0021-stage-local-console-login.md`（依現有 ADR 格式）：舞台僅限本機、控制台需管理者登入、不支援公開網路；記錄捨棄的替代方案（只綁 localhost、bearer token、mTLS）。
- 新增 `CODING_STANDARDS.md`（審查時讀，不在實作時讀），只放判斷題：
  1. 代表路徑、目錄或 URL 的請求欄位必須限制在伺服器管理的清單內。
  2. 其他執行緒（TTS、渲染）回到 session 必須經 `call_soon_threadsafe`；loop 不存在時不得直接執行。
  3. async handler 內可能超過約 50 ms 的工作（解碼、模型載入、ffmpeg、檔案 IO）進 `asyncio.to_thread`。
  4. 覆寫或刪除使用者資產須檢查使用中狀態並走回收桶。
  5. 名稱含 sanitize 的函式必須真的跳脫 HTML，否則改名。
- `AGENTS.md`：新增一行指向 ADR 0021；Validation 區塊改為一行指向 `.github/workflows/ci.yml`；說明「rebranding audit」即 `scripts/check-integration.py`。保持 AGENTS.md 精簡。

完成：三個檔案到位、`scripts/check-integration.py` 與 `tests/test_branding_compliance.py` 通過。

## Comments
