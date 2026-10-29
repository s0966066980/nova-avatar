<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# ruff 安全與 async 規則
Status: resolved
Blocked by: 04, 06, 07, 08, 09

依[規格](../spec.md)「驗收」。`pyproject.toml` 的 ruff 只選 `E9,F63,F7,F82`。

- 加入 `S102,S113,S301,S310,S605,ASYNC210,ASYNC220,ASYNC230,ASYNC240,ASYNC251`；`tests/**` 排除 `S101`。範圍沿用現有 include/extend-exclude。
- 修正剩餘命中；確屬安全者（例如 `scripts/ragflow_connection.py` 的固定 loopback `urlopen`）以行內 `# noqa: S310` 並附理由。

完成：`uv run ruff check .` 綠；故意加入 `requests.get(url)` 無 timeout 時失敗。

## Comments

### 2026-10-29

- `pyproject.toml` 的 `[tool.ruff.lint]` 加入十條 `S`/`ASYNC` 規則，新增 `per-file-ignores` 讓 `tests/**` 排除 `S101`；include/extend-exclude 不變。
- 回歸測試 `tests/test_ruff_security.py`（governance）：以 stdin 餵給 `ruff check --config pyproject.toml`，每條規則各有一段違規範例必須只觸發該規則；`requests.get(url)` 無 timeout 觸發 `S113`、加 timeout 則通過；`tests/`、`scripts/` 同樣受檢；`S101` 只在 `tests/**` 豁免。改設定前 13 項失敗。
- 修正剩餘 15 筆命中：
  - `src/server/routes/video.py`：下載前的存在檢查改為 `await asyncio.to_thread(os.path.isfile, ...)`（目錄不再被當成檔案）。
  - `scripts/cosyvoice_fastapi_server.py`：六處重複的暫存檔清理收斂為 `_remove_temporaries()`。
  - 行內 `noqa` 附理由：`ragflow_connection.py` 固定 http:// loopback／docker gateway 的 `S310`（7 處）；`benchmark-compositor.py` 執行本 repo git 基準版本的 `S102`；`benchmark-prewarm.py` 啟動後端時 loop 閒置的 `ASYNC220/230`；`test_event_loop_blocking.py` 假 ffmpeg 的 `ASYNC240`。
- 未處理（範圍外）：CosyVoice 伺服器的 `async def` 端點仍在 event loop 上同步跑首段推論與暫存檔 I/O；此為獨立單模型程序，改成 `def` 會讓推論並行，需另評估。
- 本機：ruff、check-integration 通過；pytest 1045 passed、3 skipped，2 failed 為已知 worktree 基準失敗；前端 lint、204 測試、build 通過。
