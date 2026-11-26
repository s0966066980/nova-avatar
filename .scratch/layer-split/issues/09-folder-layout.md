<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 搬到新的資料夾結構
Status: ready-for-agent
Blocked by: 07, 08

依規格決定 5、17、「依賴管理的補充」與 ADR 0028。

- `src/` 依規格決定 3 的表格搬到 `core/`、`avatar/`、`services/stt/`、`services/llm/`、`services/tts/`。
  - Python 套件名稱要加上前綴，例如 `nova_core`、`nova_render`、`nova_stt`、`nova_llm`、`nova_tts`、`nova_contracts`，避免和 PyPI 上的 `llm`、`tts` 等套件撞名。實作前先和維護者確認最後的名稱。
  - `src/avatars/musetalk` 原本就有自己的 `pyproject.toml`，連同它一起搬到 `avatar/`。
- 每一層有自己的 `pyproject.toml`、`tests/` 和 `README.md`。README 說明這一層的職責、對外介面、引擎清單與測試方式。
  - 根專案以 path 依賴引用各層，共用根目錄的 `uv.lock`。
- 各層的 setup 與權重腳本搬到 `services/<層>/scripts/`；跨層的啟動腳本留在根目錄 `scripts/`。
- 授權與來源標示：
  - 搬移時保留每個檔案的上游 notice 與 `Modified by HongXian0903, 2026` 標示；
  - 同步更新 `docs/source-attribution-audit.md`、`NOTICE`、`THIRD_PARTY_NOTICES.md` 中提到的路徑，以及 `scripts/check-integration.py` 的檢查路徑。
- 文件：更新 `README.md` 的資料夾說明、`docs/software-stack.md`、`docs/installation.md`，以及 `AGENTS.md`、`docs/agents/*` 中的路徑。
- 驗收：
  - CI 全部通過，包括改名稽核；
  - `scripts/start-all.sh` 在場域主機上能正常啟動，舞台與控制台行為不變；
  - codebase-memory 索引重新建立。
