<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# N 選一路由
Status: ready-for-agent
Blocked by: 01

依[規格](../spec.md)「任意角色直接交接」「追問留在目前角色」「天氣工具」。

- 路由結果改為「目的成員 id 或 clarify」；提示列出所有啟用成員（含主數位人）的名稱、專長介紹、交接規則與工具，並標示目前角色與其最近對話；延續追問留在目前角色。JSON schema 以啟用成員 id 為列舉。
- 天氣專屬的路由文字與欄位只在組合中有天氣工具成員時加入；關鍵字初篩從任何目前角色導向天氣工具持有者。
- `speculative_plan`（ADR 0022）推廣到 N 位。
- 擴充 `scripts/eval_llm_quality.py` 題組：每位成員的交接題、任意兩位之間的直接交接、延續追問、混合主題；E2B 路由正確率在 Comments（實機）。

## Comments
