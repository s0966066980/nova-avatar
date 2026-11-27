<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# nova-contracts

核心與各處理層之間唯一共用的型別（ADR 0027、ADR 0028）。Python 套件名稱是 `nova_contracts`，只依賴 Pydantic。

## 內容

| 模組 | 內容 |
|---|---|
| `nova_contracts` | `CONTRACT_VERSION` |
| `nova_contracts.common` | `ContractModel`（所有 DTO 的基底：不可變、拒絕未知欄位）、`ServiceHealth`、`ErrorBody`、`ServiceError` |
| `nova_contracts.http` | 描述 loopback HTTP 形狀的 `HttpApi`／`HttpOperation`，以及由它產生 OpenAPI 的 `openapi_document` |
| `nova_contracts.stt` | 語音轉文字：DTO、`SttService` Protocol、`HTTP_API` |
| `nova_contracts.llm` | 回答模型：口語文字增量等回覆事件（工單 07 第 2 步補上 `LlmService`） |
| `nova_contracts.tts` | 語音合成：可播回覆片段、聲音（`TtsVoice`）、音訊庫、聲線模型試聽、聲線訓練（語料、自動逐字稿、訓練工作）的 DTO，`TtsService` Protocol 與 `HTTP_API`；只在同一行程內使用的 `AudioSink`、`SpeechChannel`、`TtsRuntime` |
| `nova_contracts.avatar` | 數位人渲染：`AvatarService`（模型載入、人物素材、匯入、嘴型畫質、舞台背景）、每場對話的 `AvatarRenderer`、DTO。渲染器留在核心行程內，沒有 `HTTP_API` |

## OpenAPI

`openapi/<層>.json` 由各層模組的 `HTTP_API` 產生，提交進 repo。修改模型後重新產生：

```bash
uv run --no-sync python scripts/generate_openapi.py
```

CI 執行 `scripts/generate_openapi.py --check`，提交的檔案過期時失敗。

## 版本

契約不另外編版號。`CONTRACT_VERSION` 只在拆成行程後，供服務在 `GET /health` 回報、核心比對；做破壞性變更時，在同一個 PR 內修改它與核心、處理層。

## 測試

```bash
uv run --no-sync pytest core/tests/test_contracts.py
```

契約的規則測試（每個服務方法恰好對應一個 HTTP 操作、提交的 OpenAPI 是否過期等）放在 `core/tests/test_contracts.py`：其中一個案例用核心的 `TurnContext` 建立 envelope，而 `contracts/` 的測試不得依賴核心，所以本資料夾沒有自己的 `tests/`。各層對契約的測試在各層的 `tests/`（不需要核心時）或 `core/tests/`。
