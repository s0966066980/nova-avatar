<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 依賴鎖定與 CI
Status: ready-for-agent

依[規格](../spec.md)。`uv.lock` 列在 `.gitignore`，CI 以 `uv pip install` 現解依賴，CI 測到的版本與場域主機不同。

- 從 `.gitignore` 移除 `uv.lock` 並提交現有 lock。
- `.github/workflows/ci.yml` 新增 `uv lock --check`（lock 與 `pyproject.toml` 不一致即失敗）；保留現有 CPU torch 安裝方式。
- 新增不阻擋的 `npm audit --omit=dev` 步驟（`continue-on-error: true`）。

完成：lock 已追蹤；`uv lock --check` 在本機通過；改動 `pyproject.toml` 依賴而不更新 lock 時該步驟失敗。

## Comments
