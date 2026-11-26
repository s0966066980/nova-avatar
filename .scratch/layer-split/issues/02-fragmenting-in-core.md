<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 可播回覆片段改由核心切分
Status: ready-for-agent
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
