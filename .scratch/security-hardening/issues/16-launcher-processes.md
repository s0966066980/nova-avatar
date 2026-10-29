<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 啟動腳本程序管理
Status: ready-for-agent
Blocked by: 15

依[規格](../spec.md)。

- 清埠（`scripts/start-all.sh:107-120,139-140`、`start-frontend.sh:120-140`、`start-backend.sh:97-120`）殺掉占用 3000/8010 的任何程序，start-all 2 秒即 SIGKILL（start-backend 給 20 秒），SIGKILL 略過 atexit，CosyVoice（`src/tts/cosyvoice_runtime.py:500` 分離啟動）成孤兒占 GPU。改為只處理 cmdline 屬於 Nova 的程序（參考 `src/llm/llamacpp.py` 的比對方式），其他程序占埠則報錯退出；正常結束寬限統一。
- `start-all.sh:58-62` 在父程序被殺後才 `pkill -P`，子程序已成孤兒。改以 `setsid` 啟動並 `kill -- -PGID` 收整個 process group；結束時確認 CosyVoice 已停止。
- `start-all.sh:124-133`：RAGFlow 啟動失敗（含 `sudo systemctl start docker` 提示、180 s `--wait` 逾時）在 `set -e` 下擋掉整個服務。改為非致命：記錄警告，avatar 照常啟動。
- `scripts/post_musetalk_install.sh:54-61,81-83`：修補對象改為專案 `.venv`；缺檔改為失敗退出。

完成：更新 `tests/test_startup_scripts.py` 覆蓋上述行為；完整 CI 通過。

## Comments
