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

## Comments

- 2026-11-27：契約套件、adapter 與 OpenAPI 一致性檢查已完成；「核心只依賴 `contracts` 與 adapter 入口」尚未完成，狀態維持 `ready-for-agent`，只剩這一項。
- 已完成：
  - `contracts/`（套件名 `nova_contracts`，自己的 `pyproject.toml`，只依賴 Pydantic，根專案以 path 依賴引用並共用 `uv.lock`）：STT／LLM／TTS 的請求、回應與串流事件模型（LLM 事件以 `type` 欄位區分）、`SttService`、`LlmService`、`TtsService`、`AvatarRenderer` 與 `AudioSink`、`SpeechSource` Protocol、`PlayableFragment`／`TurnEnvelope`、`CONTRACT_VERSION`。
  - 工單 02、03 暫放的型別已搬進來：`PlayableFragment`、`TurnEnvelope`、`AudioSink`、`SpeechSource`／`SpeechFactory`（原位置改為重新匯出）。
  - in-process adapter：`src/asr/adapter.py`（`SttAdapter`）、`src/llm/adapter.py`（`LlmAdapter`：`route`、`generate_greeting`、`stream_reply`）、`src/tts/adapter.py`（`TtsAdapter`：`synthesize`、`flush`）。
  - 核心已經改走 adapter 的路徑：交接判斷（`src/profiles/routing.py` 經 `LlmAdapter.route`）。
  - OpenAPI：`contracts/nova_contracts/openapi.py` 由模型產生 `contracts/openapi/{stt,llm,tts}.json`；`scripts/generate-openapi.py` 重新產生，`--check` 驗證一致，已加入 CI；`contracts/tests/test_contracts.py` 同時檢查一致性。
  - CI 安裝步驟加上 `-e ./contracts`（因為 CI 用 `--no-sources`，path 依賴不會自動解析）；已用 `uv pip install --dry-run` 確認可解析。`tests/test_dependency_lock.py` 的暫存複製也納入 `contracts/pyproject.toml`。
- 未完成：核心仍直接 import 各層的內部模組（盤點：`src.llm.service` 11 處、`src.llm.llamacpp` 6 處、`src.tts.voice_library` 10 處、`src.tts.cosyvoice_runtime` 8 處、`src.avatars.catalog` 6 處、`src.scene.service` 7 處，以及 ragflow、web_search、聲線訓練等）。這些大多是管理功能（聲線庫、訓練、CosyVoice、角色目錄、場景），不屬於 `SttService`／`LlmService`／`TtsService`／`AvatarRenderer` 四個執行期 Protocol 的範圍；語音辨識（`voice_session._asr` 直接用 dict 結果，含信心值）與 TTS 也還沒改成走 adapter，因為既有測試大量使用手寫替身。建議另開工單：
  1. 在契約補上管理功能的介面（聲線庫、訓練、角色目錄、場景），或明確把它們定義成「核心的 library」而不是處理層；
  2. 再把核心逐項改成只依賴 adapter，並在 import-linter 加上「核心只能 import `nova_contracts` 與各層 `adapter`」的契約。
