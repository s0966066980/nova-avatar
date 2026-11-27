<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 搬到新的資料夾結構
Status: ready-for-human
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

## Comments

- 2026-11-27：搬移完成；場域主機的啟動驗證待人工。套件名稱經維護者確認採 `nova_` 前綴。
  - 資料夾與套件：`core/nova_core`（含 server、vad、profiles、config、greetings、utils）、`avatar/nova_render`（含 `scene/`、`musetalk/`）、`services/stt/nova_stt`、`services/llm/nova_llm`（含 `ragflow/`、`web_search/`）、`services/tts/nova_tts`，加上工單 07 的 `contracts/nova_contracts`。全部用 `git mv`，保留歷史與每個檔案的上游標示。
  - 每一層有自己的 `pyproject.toml`（依賴宣告）、`README.md`、`tests/`；根專案以 path 依賴引用並共用 `uv.lock`，本身不再出貨任何 Python 套件（`[tool.setuptools] packages = []`）。層專屬的第三方依賴（edge-tts、ddgs、faster-whisper、sherpa-onnx、opencc、pypdfium2、regex）從根專案移到所屬層。
  - 所有 `src.*` import 與路徑字串（程式、測試、腳本、文件、設定）以腳本改寫；`Path(__file__).parents[N]` 與 `sys.path` 的根目錄深度另行修正；啟動腳本改為 `core/nova_core/server/app.py`（`python <script> --help` 與 `-m nova_core.server.app --help` 驗證可啟動）。
  - 測試依 import 的層分類搬到各層 `tests/`：單一層的 → 該層（TTS 19、LLM 8、渲染 5、STT 1）；碰到核心或跨層的 65 個 → `core/tests/`；整個 repo 層級的稽核與腳本測試（9 個）與共用假物件留在 `tests/`。`tests/conftest.py` 移到根目錄 `conftest.py`；`testpaths` 明列各目錄。測試總數 2216，搬移前後相同。
  - 稽核與文件：`NOTICE`、`THIRD_PARTY_NOTICES.md`、`docs/source-attribution-audit.md`、ADR、`README.md`（新增「程式碼結構」）、`AGENTS.md`、`docs/*` 的路徑都已更新；`scripts/check-integration.py` 通過。`.scratch/` 的歷史工單沒有改寫，裡面的舊 `src/...` 路徑是當時的紀錄。
  - import-linter 契約改為 `root_packages` 多套件寫法；CI 安裝步驟因為 `--no-sources` 而明列每個 workspace 套件（已用 `uv pip install --dry-run` 驗證可解析）。codebase-memory 索引已用 `index_repository` 重建。
  - `nova_core.utils` 仍是各層共用的小工具；處理層可以 import 它，但它不是契約套件的一部分。拆成行程時需要把它獨立出來或複製進各服務。
- 與工單原文的差異：多數 TTS／LLM 的整合測試因為會 import 核心的設定載入、`ProfileStore` 或 `server.app`，被分類到 `core/tests/` 而不是各層 `tests/`。
- 待人工：在場域主機執行 `scripts/start-all.sh`，確認舞台與控制台行為不變（這個工作階段沒有啟動真實伺服器、GPU 與權重）。
