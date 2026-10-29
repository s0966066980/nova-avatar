<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# RAGFlow 檢索速度
Status: needs-triage
Blocked by: 06

依[規格](../spec.md)與 [ADR 0022](../../../docs/adr/0022-run-routing-retrieval-and-answer-concurrently.md)。issue 06 實測（`after-06-2026-10-30.json`）：檢索上限 400 ms，24 輪中 22 輪 `timeout`；串行時期檢索本身 P50 0.50–0.58 s、P95 0.77–0.85 s。上限幾乎每輪落空，等於關閉 RAG。

- 拆解 `src/ragflow/client.py` 檢索請求的耗時：bge-m3 查詢嵌入（11435 Ollama）、Elasticsearch 檢索、RAGFlow 本身處理；在 Comments 記錄各段。
- 試可降低延遲的設定（嵌入常駐與暖機、`page_size`、關閉不需要的後處理、查詢嵌入快取），每項以 issue 01 工具量測。
- 依結果與使用者決定的取捨調整上限（見 Comments），並更新 ADR 0022 的數字。

## Comments
