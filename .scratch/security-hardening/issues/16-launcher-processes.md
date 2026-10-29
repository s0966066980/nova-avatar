<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 啟動腳本程序管理
Status: resolved
Blocked by: 15

依[規格](../spec.md)。

- 清埠（`scripts/start-all.sh:107-120,139-140`、`start-frontend.sh:120-140`、`start-backend.sh:97-120`）殺掉占用 3000/8010 的任何程序，start-all 2 秒即 SIGKILL（start-backend 給 20 秒），SIGKILL 略過 atexit，CosyVoice（`src/tts/cosyvoice_runtime.py:500` 分離啟動）成孤兒占 GPU。改為只處理 cmdline 屬於 Nova 的程序（參考 `src/llm/llamacpp.py` 的比對方式），其他程序占埠則報錯退出；正常結束寬限統一。
- `start-all.sh:58-62` 在父程序被殺後才 `pkill -P`，子程序已成孤兒。改以 `setsid` 啟動並 `kill -- -PGID` 收整個 process group；結束時確認 CosyVoice 已停止。
- `start-all.sh:124-133`：RAGFlow 啟動失敗（含 `sudo systemctl start docker` 提示、180 s `--wait` 逾時）在 `set -e` 下擋掉整個服務。改為非致命：記錄警告，avatar 照常啟動。
- `scripts/post_musetalk_install.sh:54-61,81-83`：修補對象改為專案 `.venv`；缺檔改為失敗退出。

完成：更新 `tests/test_startup_scripts.py` 覆蓋上述行為；完整 CI 通過。

## Comments

### 2026-10-29 實作結果

- 新增 `scripts/process-control.sh`（三支啟動腳本共用；`lib/` 被 `.gitignore` 忽略故放在 `scripts/`）：清埠只停止指令列符合且屬本專案（指令列含專案路徑或 cwd 在專案內）的程序，其他程式占用 3000／8010 報錯退出並列出 PID；SIGTERM 寬限統一為 `NOVA_STOP_GRACE_SECONDS`（預設 20 秒），逾時才 SIGKILL。
- `start-all.sh`：清埠移到建置與 RAGFlow 之前；後端以 `exec setsid` 啟動自成程序群組，結束（含後端自行結束）時 `kill -- -PGID` 整組收尾，收尾期間忽略 INT／TERM；啟動前與結束時停止本專案殘留的 CosyVoice（比對「直譯器 `$PROJECT_ROOT/scripts/cosyvoice_fastapi_server.py`」）。`start-backend.sh` 清埠後同樣清孤兒 CosyVoice。
- RAGFlow：`ensure-docker`（含 sudo 失敗）或 `up`（含 `--wait`／就緒逾時）失敗改為警告；若為本次帶起則先 `down`，avatar 照常啟動。README、`docs/ragflow.md` 同步更新。
- `post_musetalk_install.sh`：只修補 `$PROJECT_ROOT/.venv`（不理會 `VIRTUAL_ENV`／系統 Python），找不到 mmdet 或修補失敗即退出；補上 `Modified by HongXian0903, 2026`。票面行號與現檔不符，依內容實作。
- 測試：`tests/test_startup_scripts.py` 27 項全過（新增：他程式占埠不殺、舊 Nova 程序先 TERM、忽略 TERM 於寬限後 KILL、只清本專案 CosyVoice、後端自行結束／啟動腳本被停止時整組與 CosyVoice 皆收掉、RAGFlow 失敗非致命、post_musetalk 兩項）。測試以假 `lsof`／`ss` 與 tmp 目錄替身程序進行，未觸及本機真實 3000／8010。
- 驗證：ruff、check-integration 通過；pytest 927 passed、3 skipped（僅兩項已知 worktree 基線失敗）；web lint、test（202）、build 通過。
- 未處理：llama-server 同以 `start_new_session` 啟動，後端被 SIGKILL 時也可能成孤兒；本票範圍只含 CosyVoice。
