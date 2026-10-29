<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 模型資訊查詢移出每輪路徑
Status: ready-for-agent

依[規格](../spec.md)。`src/llm/context_usage.py:68-88`（10/29 新增）每輪先呼叫 llama-server 的 `/props`、`/apply-template`、`/tokenize`，約 0.2–0.4 s，計入「LLM 初始化時間」。

- `/props` 於模型載入或切換時取一次並快取。
- Context 用量改為回覆完成後非同步計算，或以本地估算取代每輪 tokenize，不阻塞主回答。
- 路由每次新建 OpenAI client、RAG 每次新建 aiohttp session：改為重用。

完成：主回答開始前不再有這三支呼叫的回歸測試；Context 用量顯示仍正確。

## Comments
