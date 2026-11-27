<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# `CODEOWNERS` 與 CI
Status: ready-for-human
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

## Comments

- 2026-11-27：完成；需要在 GitHub 上實際跑一次來確認 CI 時間。
  - `.github/CODEOWNERS`：依 `contracts/`、`core/`、`avatar/`、`services/{stt,llm,tts}/`、`web/` 分段，每段加註解說明所屬的處理層，另有 repo 層級的 `.github/`、`scripts/`、`tests/`、`docs/`；全部填 `@s0966066980`。沒有開啟 `main` 的 branch protection。
  - `scripts/select-tests.py` 依異動檔案挑選要跑的 Python 測試，`tests/test_select_tests.py` 驗證規則：
    - 只改某一層（STT、LLM、TTS、渲染）→ 該層的 `tests/` 加 `core/tests/`（整合測試），不跑其他層；
    - 改 `contracts/`、`core/`、根目錄的 `pyproject.toml`／`uv.lock`／`conftest.py`、`tests/`、`scripts/`、`.github/` 或設定檔 → 全部測試；
    - 只改文件或 `web/` → 不跑 Python 測試；未知位置 → 全部測試（保守）。
  - CI 的 `python` job：checkout 加 `fetch-depth: 0` 以便比對；新增「Select the tests this change can affect」步驟，`pytest` 只跑被選中的路徑，沒有要跑的就略過；lint、型別檢查、`lint-imports`、OpenAPI 一致性、`check-integration.py` 每次都跑。新分支或找不到基準 commit 時跑全部。
- 與工單原文的差異：「改 `services/stt/` 的 PR 不會觸發 TTS 與渲染的測試」成立，但會一併跑 `core/tests/`，因為其中有跨層的整合測試（其中包含碰到 TTS 的整合測試，不是 TTS 層自己的測試）。
- 待人工：CI 時間沒有在 GitHub 上量測。只改單一層時測試量明顯減少、其他情況與以前相同，lint 與稽核步驟沒有增加；`fetch-depth: 0` 會多一點 checkout 時間。請在第一次 push 後看實際時間。
