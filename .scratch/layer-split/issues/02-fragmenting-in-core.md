<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 可播回覆片段改由核心切分
Status: ready-for-human
Blocked by: 01

依規格決定 12 與 ADR 0027。

- 目前 `src/llm/base.py` 直接使用 `src.server.reply_streaming.fragmenter` 的 `SemanticFragmenter` 和 `SemanticWaitTimer`，由 LLM 自己把文字切成片段。
- 改成以下分工：
  - LLM 層只產生「口語文字增量」，以及看板、檢索參考、網頁來源等結構化事件。這些事件的型別先在 LLM 層定義成資料類別，工單 07 再移到 `contracts/`。
  - 核心負責切分完整語意邊界、套用語意等待上限，並處理回覆背壓。
- `src/llm/engines/openai.py` 使用的 `timed_stage` 量測改由呼叫端（核心）負責；或者把量測工具移到 `src/utils`，前提是它不依賴核心的狀態。
- 回覆語音串流與舊有回覆模式的字幕、播放、錯誤恢復保證都不變（ADR 0007、0011）。
- 驗收：
  - 現有的串流、輪次隔離與插話測試全部通過；
  - 刪除工單 01 例外清單中對應的條目；
  - 首音延遲與修改前相比，P50 增加不超過 50 ms、P95 增加不超過 100 ms。

## Comments

- 2026-11-27：程式與測試已完成，只剩實機量測首音延遲。
  - `BaseLLM.generate_response` 與 `llm_response` 新增 `fragmenter_factory`，LLM 層只把口語文字增量餵給它（`src/llm/fragments.py` 定義 `FragmentStream`／`FragmenterFactory`，沒有注入時直接逐段轉發，不再自行切分）。
  - 核心的 `make_fragmenter_factory(config)`（`src/server/reply_streaming/fragmenter.py`）依 `reply_streaming` 設定建立 `SemanticWaitTimer`，預設值與修改前相同；`VoiceTurnSession` 在每輪呼叫時傳入。
  - `timed_stage`、`observe_stages` 與 `STAGE_NAMES` 移到 `src/utils/stage_timing.py`，`metrics.py` 重新匯出，既有匯入不變。
  - 已刪除 `src.llm.base -> ...fragmenter` 與 `src.llm.engines.openai -> ...metrics` 兩條例外。
  - 直接呼叫 `generate_response` 並依賴語意切分的測試，改為傳入核心的工廠。
- 待人工：專案伺服器目前沒有在跑，無法在這個工作階段量測。請在場域主機啟動後，以 `scripts/measure_first_audio.py` 量測，確認 P50 增加不超過 50 ms、P95 不超過 100 ms。程式路徑只多一次函式呼叫，預期沒有可量得出的差異。
- 注意：`web_guard`（網頁來源回覆）在沒有注入切分器時，是逐增量檢查而不是逐片段；核心路徑一律注入，所以實際行為不變。
