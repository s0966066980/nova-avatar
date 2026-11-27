<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 交接判斷、天氣工具、AI 招呼生成歸 LLM 層
Status: resolved
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

## Comments

- 2026-11-27：完成。
  - 交接判斷：邏輯搬到 `src/llm/handoff.py`，入口是 `route(config, members, current_id, text, history, confirmed, ...)`。`members` 是核心整理好的純 dict 清單（`id`、`name`、`main`、`description`、`rules`、`weather`），只有天氣持有者的 `weather` 帶場域預設縣市與鄉鎮；失敗拋 `RoutingError`。
  - 核心的 `src/profiles/routing.py` 變成薄包裝：從角色庫整理 `members`、把 `RoutingError` 轉成 `ProfileError`、依對話語系套用固定回覆翻譯；`route_question`、`candidates`、`weather_member`、`route_schema`、`RoutingClients`、`CLARIFY` 維持原名，呼叫端與既有測試不用改。
  - 天氣：`weather.py`、`weather_keywords.py` 從 `src/profiles/` 搬到 `src/llm/`（用 `git mv`，保留歷史與上游標示）。
  - 招呼語：AI 生成搬到 `src/llm/greeting.py`（`generate_greeting`，失敗拋 `GreetingGenerationError`）；預寫文案的隨機選取、設定驗證與排程仍在 `src/greetings/`。`visible_length` 移到 `src/utils/visible_text.py`，兩邊共用。
  - ADR 0022 的並行由核心照舊同時發出交接判斷與回答請求，這張沒有改動。
- 與工單原文的差異：驗收寫「`src/profiles` 不再 import 任何 `src.llm` 的內部模組」。這一張只搬走了交接判斷、天氣與招呼生成；`src/profiles` 與 `src/greetings` 仍會 import `src.llm.service`、`src.llm.endpoints`、`src.llm.rules`、`src.llm.llamacpp` 與新搬入的模組。核心改成只經由各層 adapter 入口呼叫，屬於工單 07 的驗收（「核心不再 import 任何處理層的內部模組」），留到那時處理。
- 新增 `tests/test_llm_handoff.py`，不經過核心直接驗證 LLM 層的交接判斷。
- 既有的測試衛生問題（非本次造成）：`tests/test_reverse_role_handoff.py`、`tests/test_role_coordinator.py` 執行時有些路徑會用預設端點真的對外送請求（回 401），輸出中可見 `AuthenticationError`。測試仍通過，但建議另開工單讓這些測試一律注入假的 client。
