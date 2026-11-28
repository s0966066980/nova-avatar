<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# nova-llm

回答模型處理層（ADR 0027）。Python 套件名稱是 `nova_llm`，內含 `ragflow`（選用的知識庫檢索）與 `web_search`（有界的網頁搜尋）兩個子套件。

## 職責

- 依對話內容產生回覆：只送出口語文字增量與結構化事件（看板等），片段切分由核心負責。
- 交接判斷（`handoff`，誰來回答這一輪）、天氣工具（`tools/weather*`）、AI 招呼生成（`greeting`）。
- 本機 llama.cpp 伺服器的生命週期（`llamacpp`）、各模型旁的描述檔（`model_profile`，宣告看圖用的投影權重配對，見[對話附件指南](../../docs/guides/conversation-attachments.md)）、回覆規則與提示詞（`rules`、`prompts`）。
- 檢索與網頁證據：RAGFlow 只做檢索（ADR 0013）；網頁搜尋在回答前有時間上限（ADR 0024）。

輪次狀態（對話紀錄的持有、角色組成、舞台）由核心持有；本層只持有自己的資產，每個請求帶齊它需要的內容。

## 對外介面

- `nova_llm.adapter.create_llm_service()`：回傳 `nova_contracts.llm.LlmService`（`reply`、`review_fragment`、`route_handoff`、`generate_greeting`、`weather_tool` 等）。
- `nova_llm.config_section`：核心的設定載入器用它遷移、驗證與匯出 `llm` 設定段落，並建立 `LlmSettings`、`LlmSession`。
- 其餘模組是內部實作，核心不得 import（import-linter 契約 `llm-internals-private`）。
- 型別與 loopback HTTP 形狀（拆成行程後使用）在 [`nova_contracts.llm`](../../contracts/README.md)。

## 引擎

| 引擎 | 選用方式 | 備註 |
|---|---|---|
| OpenAI 相容端點 | `llm.engine` 空白或 `openai-compatible`（預設） | 共用 `OpenAILLM`；端點與模型在 `config/config.yaml` 的 `llm.endpoints`，服務型別（`llm.type`）可為 `openai`、`gpt`、`dashscope`、`qwen`、`claude`、`ollama`、`vllm`；本機 llama.cpp 與雲端端點都走這條路 |
| fake | `llm.engine: fake` | 只供測試，回傳固定的口語文字增量與看板事件，完全離線；不是端點，不出現在控制台 |

模型、權重與雲端服務的授權各自獨立，不假設與根目錄的 Apache-2.0 相同；見 [`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md)。

## 依賴

`pyproject.toml` 宣告本層自己的第三方依賴，根專案以 path 依賴引用並共用根目錄的 `uv.lock`。本層 import `nova_core.utils`（日誌、路徑、計時），但不宣告 `nova-core`，避免與核心對各層 adapter 的依賴形成循環。

## 測試

```bash
uv run --no-sync pytest services/llm
```

`services/llm/tests/` 只放不需要核心的測試（回覆協定、交接、首句規則、RAGFlow 嵌入伺服器腳本）。需要核心設定或伺服器的測試（LLM 契約、網頁搜尋、天氣、端點、問候）在 [`core/tests/`](../../core/README.md)，其中需要真實模型或本機伺服器者帶 `gpu` marker，預設排除。

## 腳本

`services/llm/scripts/`：

| 腳本 | 用途 |
|---|---|
| `ragflow.sh` | 準備、啟動、停止與驗證 RAGFlow（`install-docker`、`prepare`、`connect`、`up`、`down`、`status`、`pull-model` 等） |
| `ragflow_prepare.py`、`ragflow_validate.py`、`ragflow_connection.py` | `ragflow.sh` 呼叫的部署準備、compose 驗證與連線設定 |
| `ragflow_llamacpp_embedding.sh` | CPU-only llama.cpp 的 BGE-M3 嵌入服務（systemd 單元在 `integrations/ragflow/`） |
| `ragflow_embedding.sh` | 舊的 GPU Ollama 嵌入服務，僅供還原 |
| `configure-cwa.py` | 寫入中央氣象署金鑰到 `config/cwa.env` |

`scripts/start-all.sh` 會在 RAGFlow 已準備好的主機上呼叫 `services/llm/scripts/ragflow.sh`。
