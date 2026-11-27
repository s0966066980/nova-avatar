<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 搬到新的資料夾結構
Status: ready-for-human
Blocked by: 07, 08

依規格決定 5、17、「依賴管理的補充」與 ADR 0028。

- `src/` 依規格決定 3 的表格搬到 `core/`、`avatar/`、`services/stt/`、`services/llm/`、`services/tts/`。
  - Python 套件名稱（維護者 2026-11-26 確認，Q25）：`contracts/` → `nova_contracts`、`core/` → `nova_core`、`avatar/` → `nova_render`、`services/stt/` → `nova_stt`、`services/llm/` → `nova_llm`、`services/tts/` → `nova_tts`。加前綴是為了避免和 PyPI 上的 `llm`、`tts` 等套件撞名；`nova_avatar` 保留給整個專案。
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

### 2026-11-27 資料夾搬移

分支 `ls/09-folder-layout`（接在整合分支 `layer-split` tip ff3b9f8 之上）。四個提交：純 `git mv`、import 與路徑改寫、各層 `pyproject.toml` 與鎖檔、文件。

**舊路徑到新路徑**

| 舊 | 新（Python 套件） |
|---|---|
| `src/server`、`src/vad`、`src/profiles`、`src/config`、`src/greetings`、`src/utils` | `core/nova_core/`（`nova_core`） |
| `src/asr` | `services/stt/nova_stt/`（`nova_stt`） |
| `src/llm`、`src/ragflow`、`src/web_search` | `services/llm/nova_llm/`、`.../ragflow/`、`.../web_search/`（`nova_llm`、`nova_llm.ragflow`、`nova_llm.web_search`） |
| `src/tts` | `services/tts/nova_tts/`（`nova_tts`） |
| `src/avatars`、`src/scene` | `avatar/nova_render/`、`.../scene/`（`nova_render`、`nova_render.scene`） |
| `src/avatars/musetalk`（含自己的 `pyproject.toml`） | `avatar/nova_render/musetalk/`（深度不變，授權檔的相對路徑不用改） |
| `scripts/` 內各層專屬的 setup 與權重腳本 | `services/tts/scripts/`、`services/llm/scripts/`、`avatar/scripts/` |

`scripts/` 留下跨層的啟動、設定與量測腳本，以及 `musetalk_weights.py`（TTS 的 `breezyvoice_weights.py` 也 import 其中的 `WeightSource`、`verify`，放進任一層都會形成跨層 import）。

**依賴與鎖檔**

- 根專案以 editable path 依賴引用六個套件，`uv.lock` 只多了五個 `nova-*` 套件、所有第三方版本不變；`vad`、`musetalk`、`tensorrt` 三個 extra 移到擁有它們的層，根目錄留同名的轉接 extra，所以 `uv sync --extra musetalk`、`.[vad]` 照舊。
- `torch` 與環境共用的固定版本（`transformers`、`websockets`、`setuptools`）留在根目錄，因為 uv 只對根專案的需求套用 `[tool.uv.sources]`。
- 處理層 import `nova_core.utils`，核心 import 各層的 adapter，所以各層與核心互相不宣告依賴（否則循環）。這是規格把 `utils` 放進核心的後果；拆成行程時要處理。
- CI 的安裝步驟改成 `-e ./contracts -e './core[vad]' -e ./services/stt -e ./services/llm -e ./services/tts -e ./avatar -e .`，已在乾淨的 Python 3.11 venv（CPU 版 torch）驗證。

**測試放哪裡**

這個 repo 的處理層測試幾乎都要用核心的 `Config`、伺服器或假物件，所以規則是：只需要該層與 `nova_core.utils` 的測試放該層的 `tests/`，其餘放 `core/tests/`；不屬於任何一層的放根目錄 `tests/`。結果（測試檔數）：`core/tests` 78、`services/tts/tests` 22、`services/llm/tests` 4、`avatar/tests` 3、`services/stt/tests` 1、根 `tests/` 8。契約測試（STT／LLM／TTS）因為要載入核心設定，在 `core/tests/`；`test_contracts.py` 用核心的 `TurnContext`，也在 `core/tests/`，所以 `contracts/` 沒有自己的 `tests/`（README 說明）。共用的假物件（`tts_fakes`、`edge_fakes`、`training_fakes`）在 `services/tts/tests/`，其餘在 `core/tests/`；測試資料夾不再有 `__init__.py`，改由 `pyproject.toml` 的 `pythonpath` 讓假物件以模組名稱 import。分類與標記集中在根目錄 `conftest.py`。

**搬移時發現並修正的問題**

- `tests/test_layer_entry_points.py` 與 `core/tests/test_config_entry_points.py` 原本以 `ROOT / "src"` 找目錄，搬移後會變成「找不到任何檔案、全部通過」；已改成真正的資料夾並加上存在性斷言。
- 層邊界契約裡 `src.ragflow.*`、`src.web_search.*`、`src.scene.*` 的逐檔清單改成保護整個子套件（`nova_llm.ragflow`、`nova_llm.web_search`、`nova_render.scene`），之後新增的模組自動受保護。已用暫時加入的違規 import 確認契約會 BROKEN。
- `REPO_DATA` 若照舊用 `parents[1]` 會指到 repo 外面；`PROJECT_ROOT`、`admin.env`、模型與 `.local` 的相對路徑都依新深度更正。
- `test_server_shutdown.py` 以 `-I` 啟動子行程，不吃 `PYTHONPATH`，改成明確傳入各套件根目錄。

**驗證**（乾淨 CI 式 venv：Python 3.11、CPU torch、只做 editable 安裝、不設 `PYTHONPATH`）

- `uv lock --check` 通過；`ruff check .` 通過；`pyright` 0 errors；`lint-imports --no-cache` 11 條契約全保持、沒有 `ignore_imports`；`generate_openapi.py --check` 與 `check-integration.py` 通過。
- pytest：2380 passed、3 deselected（gpu）、63 subtests passed，與搬移前相同，沒有測試遺失。
- 覆蓋率（`--cov` 指向五個套件資料夾，與先前的 `--cov=src` 範圍相同）：在先前基準使用的共用 venv（CUDA 隱藏）為 25464 行、未覆蓋 5871，76.95%，高於基準 76.93%（25467 行、未覆蓋 5875；少 3 行是 `app.py` 移除了 `sys.path` 補丁）。CI 式 venv（CPU torch、套件組成不同）多 7 行未覆蓋，為 76.91%，屬環境差異。
- 前端：`npm ci`、`npm run lint`、`npm test`（366 通過）、`npm run build` 通過；`web/` 沒有變動。
- 以 fake 引擎設定啟動真正的入口 `core/nova_core/server/app.py`，`/health` 回報 ready、`/` 回 200；各 `.sh` 通過 `bash -n`。
- 尚未做：`scripts/start-all.sh` 在場域主機上的實機啟動（舞台與控制台行為、GPU 上的 MuseTalk 與本機 LLM），以及 codebase-memory 重建索引；狀態維持開啟。

**場域主機要注意**

- 第一次更新後先 `uv sync --inexact`（`uv run` 也會同步），讓新套件裝進 venv。
- 舊後端若仍在執行，新的 `start-*.sh` 認不出它（指令列從 `src/server/app.py` 變成 `core/nova_core/server/app.py`），會回報「埠被非本專案程式佔用」；先停掉舊的。同理，升級前留下的孤兒 `src.tts.training.whisper_worker` 不會被辨識。
- RAGFlow 的 systemd 單元：`nova-ragflow-llamacpp-embedding.service` 是 link 到 repo 內的檔案；`ragflow.sh up`（`start-all.sh` 在已準備好 RAGFlow 的主機上會執行）會重新 link 並重新載入。由 `ragflow_connection.py --setup-proxy` 寫入的 model-sync 單元寫死了腳本路徑，`up` 在使用共用 Ollama 的主機上會重寫它；沒走 `up` 的主機需手動執行一次 `python3 services/llm/scripts/ragflow_connection.py --setup-proxy`。

### 2026-11-27 剩餘驗收（交給維護者）

程式與文件的搬移已完成並通過 CI 的每一步；剩下兩項只有維護者能在場域主機上做：

1. 在場域主機執行 `scripts/start-all.sh`，確認舞台與控制台行為不變（含 GPU 上的 MuseTalk 與本機 LLM）。升級時請照上一則留言的「場域主機要注意」處理（先停舊後端、`uv sync --inexact`、RAGFlow 的 systemd 單元）。
2. 重新建立 codebase-memory 索引（`project="nova-avatar"`，見 `docs/agents/code-navigation.md`），讓查詢回傳新路徑。

兩項都完成後，把本工單改為 `Status: resolved`。
