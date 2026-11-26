<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 交接判斷、天氣工具、AI 招呼生成歸 LLM 層
Status: ready-for-agent
Blocked by: 01

依規格決定 19 與 ADR 0027。

- `src/profiles/routing.py`（交接判斷）直接使用 `src.llm.llamacpp_protocol`。把它移進 LLM 層，對外只提供一個入口，例如 `route(question, members, handoff_context)`，回傳目的角色。
  - 傳入的 `members` 包含每位成員的專長介紹與交接規則，資料由核心從當次角色組合整理後傳入。
  - 延續上一題的追問、混合主題、反向角色交接的語意都不變。
- `src/profiles/weather.py`、`src/profiles/weather_keywords.py`（CWA）移成 LLM 層內部的工具。場域預設地點由核心在請求中帶入；訪客臨時指定的地點只屬於本次對話。
- `src/greetings/content.py` 的 AI 生成改為呼叫 LLM 層的入口；預寫文案的隨機選取和排程留在核心。
- ADR 0022 的「交接判斷、檢索、回答同時進行」由核心同時發出交接判斷與回答請求來維持。
- 驗收：
  - 角色交接、反向角色交接、天氣與閒置招呼的既有測試全部通過；
  - `src/profiles` 不再 import 任何 `src.llm` 的內部模組；
  - 刪除對應的例外清單條目。
