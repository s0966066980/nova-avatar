<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 停用預設 Ollama 與顯存盤點
Status: ready-for-agent
Blocked by: 04

依[規格](../spec.md)。10/29 實測 4090 已用 22.1／24.5 GB：Nova 10.7、llama-server 6.0、Ollama（11434）1.6、不明 python 約 2.9 GB。

- 主要 LLM 改走 llama.cpp 後，啟動腳本與設定不再需要 11434 的 Ollama；保留 RAGFlow 嵌入用的 11435。文件說明如何停用。
- 盤點不明 python 程序（指令列、啟動來源）並在 Comments 回報；不終止任何程序。
- 記錄 E2B＋MuseTalk＋BreezyVoice 同時載入時的顯存。

## Comments
