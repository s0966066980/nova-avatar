<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# ruff 安全與 async 規則
Status: ready-for-agent
Blocked by: 04, 06, 07, 08, 09

依[規格](../spec.md)「驗收」。`pyproject.toml` 的 ruff 只選 `E9,F63,F7,F82`。

- 加入 `S102,S113,S301,S310,S605,ASYNC210,ASYNC220,ASYNC230,ASYNC240,ASYNC251`；`tests/**` 排除 `S101`。範圍沿用現有 include/extend-exclude。
- 修正剩餘命中；確屬安全者（例如 `scripts/ragflow_connection.py` 的固定 loopback `urlopen`）以行內 `# noqa: S310` 並附理由。

完成：`uv run ruff check .` 綠；故意加入 `requests.get(url)` 無 timeout 時失敗。

## Comments
