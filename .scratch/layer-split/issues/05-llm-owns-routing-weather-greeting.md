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

### 2026-11-26 實作完成（分支 `ls/05-llm-owns-routing`）

變更：

- 交接判斷移到 `src/llm/handoff.py`（由 `src/profiles/routing.py` 以 git mv 搬移）。對外入口是 `route(config, question, members, context)`：
  - `members` 是 `RoleCandidate` 清單，內容為每位成員的 id、名稱、是否為主數位人、專長介紹、交接規則；只有天氣工具持有者帶 `weather_site`（場域預設地點）。
  - `context` 是 `HandoffContext`，內容為目前角色、目前角色最近的對話，以及本場對話已確認的地點。LLM 層不保存任何一項。
  - 失敗時丟出 LLM 層自己的 `RoutingError`，不再使用核心的 `ProfileError`。
- 核心側的 `src/profiles/routing.py` 改成轉接層：`candidates()`、`weather_member()` 和新的 `role_candidates()` 從當次角色組合整理成員資料，`route_question()` 呼叫 `src.llm.handoff.route`，把 `RoutingError` 轉成 `ProfileError`，並用 `fixed_text` 把釐清句轉成對話語系。呼叫方式和以前相同，所以協調器、試跑路由與既有測試都不必改用法。
- 天氣工具移到 `src/llm/tools/weather.py`、`src/llm/tools/weather_keywords.py`，屬於 LLM 層內部模組。核心只透過 `src.llm.tools`（`CwaWeather`、`WeatherQuery`、`weather_prompt`）使用。
  - `config/cwa.env` 改用 `src.utils.paths.CONFIG_DIR` 定位，搬移後仍是 repo 根目錄的 `config/cwa.env`。
  - `NOVA_CWA_API_KEY`、`CWA_API_KEY` 環境變數優先的規則不變，新增測試鎖住這兩條規則。
  - 訪客確認的地點仍存在協調器的 `confirmed[sid]`，只屬於本場對話。
- AI 招呼生成移到 `src/llm/greeting.py`，入口是 `generate_greeting(config, prompt, min_chars=, max_chars=)`。
  - 包含提示組成、正規化、純文字與字數檢查、重試一次，以及兩次共用 15 秒上限。
  - 失敗時丟出 `GreetingGenerationError`，訊息與以前相同。
  - `src/greetings/content.py` 保留設定驗證、預寫文案的隨機選取（避免連續重複），由 `prepare_greeting` 把錯誤轉成 `GreetingError`；排程（`controller.py`）沒有變動。
  - 字素計數 `visible_length` 移到 `src/utils/graphemes.py`，供兩邊共用，`src.greetings.content` 仍然匯出它。
- ADR 0022 的並行要求：`voice_session` 原本就由核心同時建立交接判斷 task 與主回答，這次沒有改動，`test_concurrent_routing.py` 全部通過。
- 例外清單：工單 01 沒有為本工單登記例外條目，所以沒有條目可刪。為了防止退回原狀，新增 import-linter 契約 `core-uses-llm-entry-points`：核心（server、profiles、config、greetings、vad、utils）不得直接 import `src.llm.llamacpp_protocol`、`src.llm.tools.weather`、`src.llm.tools.weather_keywords`。已用暫時加入的違規 import 確認這條契約會 BROKEN。

驗收：

- 角色交接、反向角色交接、天氣、閒置招呼的既有測試全部通過。新增 `tests/test_llm_handoff.py`、`tests/test_llm_greeting.py`，以及 `test_cwa_weather.py` 的金鑰來源測試。
- CI 每一步都通過：`uv lock --check`、ruff、pyright、lint-imports（7 條契約 KEPT）、`scripts/check-integration.py`、pytest（2195 passed、2 skipped），web 的 lint、test、build 與 `npm audit --omit=dev`。
- `grep -rn "src\.llm" src/profiles src/greetings`：交接判斷、天氣、招呼只剩 `src.llm.handoff`、`src.llm.tools`、`src.llm.greeting` 三個入口，已沒有 `llamacpp_protocol`、`text_normalizer` 或天氣模組的 import。
- 不在本工單範圍、仍留著的 `src/profiles` → `src.llm` import：
  - `coordinator.py` 使用 `src.llm.service`（`select_session_profile`、`session_history`、`remove_session`；角色對話記憶依 ADR 0027 應歸核心）和 `src.llm.llamacpp.ensure_server`（Owned llama-server 的監督）。
  - `store.py` 使用 `src.llm.endpoints`、`src.llm.rules`（設定驗證）。
  - 這些屬於回答入口、設定驗證與行程監督，由工單 06（設定驗證）與 07（各層介面）處理。

待維護者實機驗收：

- 舞台角色交接：啟用含天氣工具成員的角色組合，在舞台依序問「介紹你們的服務」、「臺北市明天天氣如何？」（關鍵字初篩交接）、「那週末呢？」（追問留在天氣角色）、「我想問訂單」（交給客服，或反向交回主數位人）。確認交接說明、轉場與回答都和修改前相同。
- 用真實 CWA 金鑰查詢天氣：確認 `config/cwa.env`（`scripts/configure-cwa.py` 寫入）或 `NOVA_CWA_API_KEY` 有效，在控制台角色組合的「CWA 天氣查詢」看到「授權碼已設定」（`weather_configured=true`），再問一題天氣，確認回答附上中央氣象署的資料來源與時間。
- AI 閒置招呼：主數位人改用 AI 模式，在控制台「預覽」與「試播」各執行一次；舞台空場後，確認招呼依間隔播出。
