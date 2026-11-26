<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 建立 `contracts/` 與各層介面
Status: ready-for-agent
Blocked by: 06

依規格決定 5、9、18 與 ADR 0028。

- 新增 `contracts/` 套件，有自己的 `pyproject.toml`，只依賴 Pydantic。
- 在 `contracts/` 定義：
  - 各層的請求與回應模型，以及串流事件，包括 LLM 的口語文字增量、看板、檢索參考、網頁來源、交接判斷結果，以及 TTS 的片段請求。
  - 各層的 Protocol：`SttService`、`LlmService`、`TtsService`、`AvatarRenderer`。
  - 常數 `CONTRACT_VERSION`。
- 把工單 02、03 暫放在其他位置的事件與片段型別移進來。
- 核心只透過 Protocol 呼叫各層。各層提供 in-process adapter 實作這些 Protocol。
- 依規格決定 7 的傳輸方式為 STT、LLM、TTS 產生 OpenAPI，提交到 `contracts/openapi/`。新增一支腳本重新產生 OpenAPI，CI 檢查產生結果與提交的版本一致。這時還不需要真的 HTTP 伺服器。
- 驗收：
  - 核心不再 import 任何處理層的內部模組，只依賴 `contracts` 和各層的 adapter 入口；
  - OpenAPI 一致性檢查納入 CI。
