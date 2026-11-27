# nova-avatar-contracts

這個套件是各處理層之間契約的唯一來源（見 [ADR 0027](../docs/adr/0027-split-code-by-processing-layer.md)、[ADR 0028](../docs/adr/0028-monorepo-with-contracts-package.md)）。

- 只依賴 Pydantic，任何一層都可以依賴它，不必牽連其他層。
- `stt.py`、`llm.py`、`tts.py`、`avatar.py`：各層的請求與回應模型、串流事件與 Protocol（`SttService`、`LlmService`、`TtsService`、`AvatarRenderer`）。
- `turn.py`：輪次識別與可播回覆片段。
- `version.py`：`CONTRACT_VERSION`。任何另一端會察覺的變更都要調整它；拆成行程後，服務在 `/health` 回報這個值，核心遇到不符的版本就拒絕使用。
- `openapi/`：由模型產生並提交的 OpenAPI 文件。**不要手改**；修改模型後執行 `uv run --no-sync python scripts/generate-openapi.py`，CI 會用 `--check` 驗證兩者一致。

各層以 in-process adapter（`src/<層>/adapter.py`）實作這些 Protocol；核心呼叫 adapter，將來要拆成行程時只需換成 HTTP 用戶端。
