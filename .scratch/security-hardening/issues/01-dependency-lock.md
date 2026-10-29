<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 依賴鎖定與 CI
Status: resolved

依[規格](../spec.md)。`uv.lock` 列在 `.gitignore`，CI 以 `uv pip install` 現解依賴，CI 測到的版本與場域主機不同。

- 從 `.gitignore` 移除 `uv.lock` 並提交現有 lock。
- `.github/workflows/ci.yml` 新增 `uv lock --check`（lock 與 `pyproject.toml` 不一致即失敗）；保留現有 CPU torch 安裝方式。
- 新增不阻擋的 `npm audit --omit=dev` 步驟（`continue-on-error: true`）。

完成：lock 已追蹤；`uv lock --check` 在本機通過；改動 `pyproject.toml` 依賴而不更新 lock 時該步驟失敗。

## Comments

### 2026-10-29

- `.gitignore` 移除 `uv.lock`，提交現有 lock（214 套件，uv 0.11.21 產生，與 `pyproject.toml` 一致）。
- CI python job 在安裝前新增 `uv lock --check`（阻擋）；`setup-uv` 快取鍵加入 `uv.lock`；CPU torch 安裝步驟不變。
- CI web job 新增 `npm audit --omit=dev`（`continue-on-error: true`）。
- 回歸測試 `tests/test_dependency_lock.py`（governance）：lock 已追蹤、CI 步驟順序與設定；以 `uv lock --check --offline` 驗證 lock 一致，且刪除 `pyproject.toml` 一項依賴後檢查失敗（暫存目錄複本，不連網）。
- 本機：`uv lock --check` 通過；ruff、check-integration、前端 lint/test/build 通過；pytest 803 passed，2 failed 為環境依賴（worktree 無 `models/musetalk`、本機 OCR 不可用），與本單無關。
- 目前 `npm audit --omit=dev` 回報 5 個 high（`@vue/server-renderer`、`nanoid`、`postcss`、`source-map-js`），均有 `npm audit fix` 可修，未在本單範圍內，需另開單處理。
