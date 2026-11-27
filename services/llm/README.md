# LLM (`nova_llm`)

回覆、交接判斷、天氣工具、招呼生成，以及檢索與網路搜尋。目標是 loopback 服務：以 SSE 串流回覆事件（ADR 0027）。

- **內容**：`base.py`／`service.py`（回覆生成）、`handoff.py`（交接判斷）、`weather*.py`（CWA 天氣）、`greeting.py`、`ragflow/`、`web_search/`、`engines/`（OpenAI 相容與 fake）、`adapter.py`、`config_api.py`。
- **對外介面**：`nova_contracts.LlmService`，由 `adapter.LlmAdapter` 實作；LLM 層只產生口語文字增量與結構化事件，片段切分由核心負責（`fragmenter_factory`）。
- **引擎**：OpenAI 相容端點（llama.cpp、Ollama、雲端）；`llm.provider: fake` 回傳固定回覆，不出現在控制台。
- **測試**：`uv run --no-sync pytest services/llm`。

其他層與契約見 [`contracts/README.md`](../../contracts/README.md)；整體決定見 [ADR 0027](../../docs/adr/0027-split-code-by-processing-layer.md) 與 [ADR 0028](../../docs/adr/0028-monorepo-with-contracts-package.md)。
