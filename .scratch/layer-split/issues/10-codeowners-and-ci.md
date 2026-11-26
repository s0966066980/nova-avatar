<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# `CODEOWNERS` 與 CI
Status: ready-for-agent
Blocked by: 09

依規格決定 15、16。

- 新增 `.github/CODEOWNERS`，依 `contracts/`、`core/`、`avatar/`、`services/stt/`、`services/llm/`、`services/tts/`、`web/` 分段，目前全部填 `@s0966066980`。每一段加註解說明這一段屬於哪個處理層。
- 不開啟 `main` 的 branch protection。
- CI：
  - 依路徑只跑受影響的處理層測試；
  - `contracts/`、根目錄 `pyproject.toml` 或 `uv.lock` 有改動時，跑全部測試；
  - import-linter、OpenAPI 一致性、`scripts/check-integration.py` 每次都跑；
  - 確認整體 CI 時間沒有變長。
- 驗收：
  - 只改 `services/stt/` 的 PR 不會觸發 TTS 與渲染的測試；
  - 改 `contracts/` 的 PR 會跑全部測試。
