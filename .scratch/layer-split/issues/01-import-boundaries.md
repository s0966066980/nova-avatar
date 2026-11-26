<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 用 import-linter 守住處理層邊界
Status: ready-for-agent

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
