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

- 2026-11-27：完成。`pyproject.toml` 的 `[tool.importlinter]` 有 5 份契約：處理層不得 import 核心，以及 STT、LLM、TTS、數位人渲染各自不得 import 其他層。CI 新增 `lint-imports` 一步；`CODING_STANDARDS.md` 新增規則 6。
- `src/server` 原本沒有 `__init__.py`，grimp 看不到這個命名空間套件，所以補上了。
- 同一層的模組視為一組（LLM 層含 `src.llm`／`src.ragflow`／`src.web_search`，渲染層含 `src.avatars`／`src.scene`），所以 `avatars` 與 `scene` 之間、`web_search` 與 `llm` 之間的 import 不算越界。規格「現況」把 `src.avatars.base → src.scene.service` 和 `src.web_search → src.llm` 也列為越界，其實是層內依賴。
- 層與層的契約只檢查直接 import（`allow_indirect_imports`），因為間接鏈都會經過核心，而核心方向已由第一份契約管住。
- 規格沒列到的違規：`src.avatars.base → src.vad.audio`（`AudioTooLongError`），歸工單 06 清除。
- 目前例外共 15 條，編號分布：02 有 2 條、03 有 5 條、04 有 3 條、06 有 5 條。
- 本機若快取過期，`lint-imports` 可能少報；懷疑時加 `--no-cache`。
