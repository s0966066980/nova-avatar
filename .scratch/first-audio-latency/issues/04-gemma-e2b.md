<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 主要 LLM 改為 Gemma 4 E2B
Status: ready-for-agent
Blocked by: 01, 03

依[規格](../spec.md)。`gemma-4-E2B_q4_0-it.gguf`＋`gemma-4-E2B-it-mmproj.gguf` 已在 `/home/oliver/llama/`，`src/llm/llamacpp.py:359,414` 已支援（附件視覺模型）。授權 Apache-2.0（Google 官方 `google/gemma-4-E2B-it-qat-q4_0-gguf`）。

- `config/config.yaml` 預設端點與模型改為 E2B；確認思考模式關閉、看板／口語協定與 GBNF（若適用）相容、路由 JSON 可解析。9B 保留為可選。
- 品質驗收：從 `logs/voice-test-history.json` 與知識庫挑 30 題（一般、RAG、天氣、需交接），9B 與 E2B 各答一次；自動檢查格式、簡體字、字數上限、路由正確率；產生並排報告（HTML 或 Markdown）給使用者決定。
- 路由正確率明顯低於 9B 時，加關鍵字初篩，不回頭用 9B。
- 以 issue 01 工具量測前後差異。

完成：報告交給使用者並在 Comments 記錄其決定；預設切換只在使用者接受後合併。

## Comments
