<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# `CODEOWNERS` 與 CI
Status: resolved
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

### 2026-11-27 CODEOWNERS 與依路徑選測試

分支 `ls/10-codeowners-ci`（接在 `layer-split` tip 1b3703b 之上）。

**做了什麼**

- `.github/CODEOWNERS`：先放預設 `*`（根目錄設定、`scripts/`、`docs/`、`tests/`），再依 `contracts/`、`core/`、`avatar/`、`services/stt/`、`services/llm/`、`services/tts/`、`web/` 分段，每段註解說明所屬處理層，全部 `@s0966066980`。沒有開啟也沒有提到開啟 branch protection。
- `scripts/ci_select_tests.py`：把「哪些改動跑哪些測試」寫成可本機驗證的程式，不埋在 YAML。`ci.yml` 的 python job 在安裝後多一個 `select` 步驟，pytest 步驟吃它的輸出；輸出為空就是純 `pytest`（用 `pyproject.toml` 的 `testpaths`）。
- 比對基準：`pull_request` 用 `HEAD^1`（合併提交的第一個親代 = base 最新）；`push` 用 `github.event.before`；`workflow_dispatch`、`git diff` 失敗（例如新分支 before 全零、force push）或沒有任何改動，一律跑全部。checkout 加 `fetch-depth: 0`（pack 約 43 MB）。沒有使用第三方 paths-filter action，所以沒有新的 action SHA 要驗證；既有的 SHA 釘選維持不變。
- 單元測試 `tests/test_ci_select_tests.py`（8 個）：只改 `services/stt/` 不選 TTS、LLM、avatar 的測試；改 `contracts/` 選全部；各層選擇的聯集剛好等於 `pyproject.toml` 的 `testpaths`、沒有重複。

**選擇規則**

| 改動的路徑 | 跑的測試 |
| --- | --- |
| `contracts/`、`core/`（含 `core/tests/`）、根目錄 `pyproject.toml`、`uv.lock`、`conftest.py`、`.github/workflows/ci.yml`、`scripts/ci_select_tests.py`、`config/` 等任何未歸類路徑，或 `workflow_dispatch` / 無 diff | 全部（純 `pytest`） |
| `services/stt/`、`services/llm/`、`services/tts/`、`avatar/` | `core/tests`、`tests` + 被改那層自己的 `tests/` |
| `docs/`、`web/`、`.scratch/`、根目錄 `*.md`、`LICENSE`、`NOTICE`、`.github/CODEOWNERS` | `core/tests`、`tests` |

理由：

- `core/` 暗示全部：各層的測試共用 `core/tests` 的輔助模組（在 `pythonpath` 上）與根目錄 `conftest.py`，核心也是各層的唯一使用者；契約同理。
- `core/tests` 與根目錄 `tests/` 每次都跑：前者透過 adapter 與 fake 引擎檢查核心與各層的銜接，一個層的改動可能弄壞核心這一側；後者是整個 repo 的稽核（品牌、授權、鎖檔、啟動腳本、層邊界設定），文件或前端的改動也會影響它。所以「只改 STT 不觸發 TTS 與渲染的測試」指的是各層自己的 `tests/`；`core/tests` 裡使用 TTS 與渲染 fake 的核心測試仍會跑。
- 預設是全部：沒歸類的路徑寧可多跑。

**不讓 CI 變長**

- 全跑路徑與原本完全相同（同一個 job、單一次安裝、純 `pytest`）。
- 多出的成本：`fetch-depth: 0` 約數秒、select 步驟不到 1 秒；改單一層時少跑其他三層自己的測試，節省的時間遠大於此。
- 不拆成多個 job：每個 job 都要重裝依賴（含 CPU torch），反而拉長；也不另設偵測 job，避免多一次排程與 checkout。
- `web` job 維持原樣、沒有加路徑過濾：它不依賴 `core`，但前端與後端 API 契約（OpenAPI）的關係未逐一確認，不確定時不動。

**驗證**（共用 venv，以 `uv run --no-sync` 執行）

- `uv lock --check`、`ruff check .` 通過；`pyright` 0 errors；`lint-imports --no-cache` 11 條契約全保持；`generate_openapi.py --check`、`check-integration.py` 通過。
- 全部 pytest：2388 passed、3 deselected（gpu）、63 subtests passed（比搬移後多的 8 個就是新測試）。
- 收集比對：純 `pytest --collect-only` 的 2388 個測試，與 `core/tests tests`、四個層的 `tests/` 分開收集的聯集逐一相同、沒有重複。
- 以真實 git diff 模擬：只改 `services/stt/` → `core/tests tests services/stt/tests`；stt + `contracts/` 或只改 `contracts/` → 全部；只改 `docs/` → `core/tests tests`；改 `avatar/` 與 `services/tts/` → `core/tests tests avatar/tests services/tts/tests`；`--base` 為全零或省略 → 全部。
- `ci.yml` 通過 `yaml.safe_load`，各 `run` 區塊通過 `bash -n`；本機沒有 `actionlint`，未執行。

**只能在 GitHub 上驗證**

- 實際的 `pull_request` 與 `push` 事件上 `HEAD^1`、`github.event.before` 是否如預期可用（腳本在失敗時會退回全部，不會漏跑）。
- 只改 `services/stt/` 的 PR 在 Actions 紀錄中實際只跑 STT 的測試；改 `contracts/` 的 PR 跑全部。
- 整體 CI 時間與先前相比沒有變長（以上是推論，沒有實測）。
- `CODEOWNERS` 是否被 GitHub 解析無誤（Settings 或 PR 的 Files 頁會顯示）。
