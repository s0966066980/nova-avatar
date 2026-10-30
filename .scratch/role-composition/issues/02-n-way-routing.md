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

### 2026-10-30 路由回傳格式（與 03 約定）

`route_question(config, library, current_id, text, history, confirmed, *, clients=None, client_factory=OpenAI)`；`library` 只讀 `profiles` 與 `composition`（不再讀 A1 的 `pair`／`handoff`／`weather`／設定檔 `tools`）。回傳：

```python
{
  "target": "<設定檔 id>" | None,  # 主數位人或某位生效成員（composition.live_members）；None = clarify
  "clarification": "",            # 只有 target 為 None 時非空（已依語系處理）
  "context": "",                  # 交接上下文（簡短已確認事實）
  "county": "", "town": "", "kind": "", "start_date": "", "end_date": "",
                                  # 一律存在；只有 target 是生效中的天氣工具持有者時才填（kind=current|forecast）
  "accepted_at": "<ISO 時間>",
  "decided_by": "keyword" | "model",  # 關鍵字初篩或模型（05 交接試算可顯示原因）
}
```

- 候選＝主數位人＋生效成員；target 可等於 `current_id`（留在目前角色）。目前角色若已不在候選內，路由不會選它。
- 天氣持有者 helper：`routing.weather_member(library)`（生效中的持有者成員或 None）；`routing.candidates(library)`（候選 id 清單，主數位人在前）。
- coordinator 對應（03 接手；02 只做最小改動讓測試可跑）：`target_id = route["target"]`；`target is None` → 固定回覆 `clarification`；目的是天氣持有者時才查天氣；`speculative_plan()`：目前角色是天氣持有者 → `{"weather": None, "context": ""}`，否則 `{"context": ANSWER_CONTEXT}`；留在非天氣角色的路由結果回 `{"context": ANSWER_CONTEXT}`（等於推測計畫，放行並行回答）。
