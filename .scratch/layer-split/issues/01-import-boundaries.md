<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 用 import-linter 守住處理層邊界
Status: resolved

依[規格](../spec.md)決定 3、6 與「現況」。

- 在 dev 依賴中加入 `import-linter`，並在 `pyproject.toml` 寫入處理層規則：
  - 處理層（`src.asr`、`src.llm`／`src.ragflow`／`src.web_search`、`src.tts`、`src.avatars`／`src.scene`）不得 import `src.server`、`src.profiles`、`src.config`、`src.greetings`、`src.vad`。
  - 處理層之間不得互相 import。
  - 所有處理層都可以 import `src.utils`。
- 盤點目前的違規項目，逐一列入 `ignore_imports` 例外清單。每一條都在註解中標明由哪一張工單（02–06）負責清除。
- CI 新增一步 `uv run --no-sync lint-imports`。
- 在 `CODING_STANDARDS.md` 補一條規則：新增的例外必須附上工單編號。
- 驗收：
  - CI 通過；
  - 刻意加一條越界 import 時 CI 會失敗；
  - 例外清單與規格「現況」所列的項目一致。若發現規格沒列到的違規，補記到本工單的 Comments。

## Comments

### 2026-11-26 實作完成

- `pyproject.toml` 的 dev 依賴加入 `import-linter==2.15`（2.16 起要求 Python 3.11，本專案仍支援 3.10），並更新 `uv.lock`。
- `[tool.importlinter]` 共六條規則：
  - `layers-not-core`：處理層不得 import 核心（含間接 import）。
  - `stt-not-other-layers`、`llm-not-other-layers`、`tts-not-other-layers`、`avatar-not-other-layers`：處理層之間不得直接 import。這四條只檢查直接 import，因為經過核心的路徑已由第一條擋下。
  - `utils-is-shared-leaf`：`src.utils` 不得 import 處理層或其他核心模組。加這條是為了讓「只檢查直接 import」的做法成立，否則「處理層 → utils → 另一層」的路徑會漏掉。目前沒有違規。
- 例外清單共 15 條，每條在行尾以 `# ticket NN` 標明負責清除的工單：02 兩條、03 四條、04 三條、06 六條，05 沒有。
- 例外條目一旦不再相符，`lint-imports` 就會失敗（`No matches for ignored import ...`）。所以清除 import 的工單必須同時刪掉對應條目，清單不會殘留過期的例外。
- CI 新增 `uv run --no-sync lint-imports` 一步；`CODING_STANDARDS.md` 新增第 6 條：例外必須附工單編號。
- 驗證：
  - CI 各步都已在本機執行並通過：`uv lock --check`、ruff、pyright、`lint-imports`、`scripts/check-integration.py`、pytest（2188 passed、2 skipped），以及 web 的 lint、test、build。
  - 刻意在 `src/scene/service.py` 加入 `from src.server.state import state`，`layers-not-core` 失敗，exit 1。
  - 刻意在 `src/asr/base.py` 加入 `from src.tts.factory import ...`，`stt-not-other-layers` 失敗，exit 1。
  - 暫時註解掉 `src/asr/prewarm.py` 的 VAD import，`lint-imports` 回報例外條目不再相符並失敗。
  - 三項測試做完後都已還原。

### 規格「現況」沒有列到的事項

- **`src/server` 原本沒有 `__init__.py`**，是 namespace package，import-linter（grimp）看不到它，「處理層 → `src.server`」的規則因此形同虛設。這次新增了 `src/server/__init__.py`（只有 docstring），之後 `src.server.reply_streaming` 與 `src.server.state` 的違規才偵測得到。啟動方式（`python src/server/app.py`、`python -m src.server.app`）不受影響，測試全數通過。
- **`src/avatars/base.py` → `src.vad.audio`**（`AudioTooLongError`，`put_audio_file` 解碼上傳音檔時使用）：規格沒有列到，歸給工單 06。如果工單 03 把 `put_audio_file` 移出渲染層（工單 03 列出的渲染對外介面不含它），由工單 03 一併刪除這條例外。
- **`src/avatars/base.py` → `src.tts.base`**（`sanitize_speech_text`）：規格只寫了 `base.py:162` 建立 TTS（`src.tts.factory`），這條另外補記，歸給工單 03。
- 工單 05（`src/profiles/routing.py` → `src.llm.llamacpp_protocol`）和工單 06 的 config 部分（`src/config/loader.py`、`overrides.py` → 各層內部函式）都是「核心 → 處理層」的 import。本工單的規則允許這個方向，所以它們不在例外清單裡，完成與否要靠各自工單的驗收確認，import-linter 不會擋。
- `src.llm.base`、`src.llm.service`、`src.tts.base` → `src.avatars.base` 依工單 06 的描述歸給 06。如果工單 02 或 03 先讓這些 import 消失，由該工單刪除對應條目，否則 `lint-imports` 會失敗。
