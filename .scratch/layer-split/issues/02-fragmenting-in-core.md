<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 可播回覆片段改由核心切分
Status: resolved
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

### 2026-11-26 實作完成

- **新的分工**：
  - LLM 層（`src/llm/reply_events.py`）定義資料類別 `SpokenDelta`（口語文字增量，附 `llm_sequence`）與 `SpeechEnd`（口語段落結束，即使沒有句尾標點也算邊界），以及核心要實作的 `SpeechSink` 介面（`open`／`send`／`close`）。這些型別在工單 07 移到 `contracts/`。
  - `BaseLLM.generate_response` 不再切片段，也不再碰數位人：參數 `avatar_stream`、`stream_to_avatar` 改成 `speech`（核心提供的 sink）。模型每個 chunk 解析後的口語增量原樣送進 sink；沒有 sink 時直接累積成完整口語回答。
  - 核心（`src/server/reply_streaming/speech.py` 的 `ReplySpeech`）負責切出可播回覆片段：有輪次 envelope 時用 `SemanticFragmenter`＋`SemanticWaitTimer`（語意等待上限、首個片段例外、柵欄檢查都照舊），沒有時用整句切分（`TextStreamProcessor` 從 `src/llm/base.py` 搬到 `src/server/reply_streaming/sentence_fragmenter.py`）。它也負責 `fragment_sequence`、`llm_first_speech` 階段標記、即時字幕增量，再呼叫 `avatar.put_msg_txt`。
  - 身分限制與網頁語音上限必須看完整子句，仍由 LLM 判斷：LLM 在 `open` 時把 `SpokenTextReview` 交給核心，核心每切出一個片段就先請它審查，通過的片段才播放，也才算進回傳的口語回答。
  - `VoiceTurnSession` 在串流模式建立 `ReplySpeech` 交給 `llm_response`；舊有回覆模式只有在帶網頁來源時才給一個不播放的 sink，讓網頁語音仍在片段邊界上限內（與修改前相同）。`/asr` 舊路由給不帶輪次的 sink，維持整句送出。
- **`timed_stage`**：計時工具搬到 `src/utils/stage_timing.py`（`observe_stages`、`timed_stage`），不依賴核心狀態。階段名稱的驗證改由核心的 `TurnMetrics.record_stage_duration` 負責。
- **例外清單**：刪除 02 的兩條（`src.llm.base -> src.server.reply_streaming.fragmenter`、`src.llm.engines.openai -> src.server.reply_streaming.metrics`），以及標為 06 的 `src.llm.base -> src.avatars.base`（`BaseLLM` 不再需要 `BaseAvatar` 型別）。
- **行為差異**：只有不帶輪次的整句模式（只有 `/asr` 舊路由使用）會在口語段落結束時就送出最後一句，不再等看板 JSON 生成完；文字內容不變。其他路徑的切分、字幕、播放與錯誤恢復保證不變（ADR 0007、0011）。
- **測試**：新增 `tests/test_reply_speech_seam.py`（LLM 送出未切分的增量；核心切片、依序送出、套用審查、舊路由整句送出）與 `tests/test_web_search.py` 的舊有模式網頁回答案例；既有呼叫 `generate_response(..., avatar)` 的測試改經 `tests/speech_fakes.py` 的 `spoken_answer`（與核心相同的接法）。串流、輪次隔離（fence、計時釋放）、插話與首個片段例外的既有測試全部通過。
- **驗證**：`uv lock --check`、`ruff check .`、`pyright`、`lint-imports`、`scripts/check-integration.py`、`pytest`（2195 passed、2 skipped）、`web` 的 lint／test／build 全部通過。

### 待維護者實機驗收：首音延遲

切片的位置從 LLM 執行緒搬到核心，但仍在同一執行緒、同一把鎖內完成，每個增量只多一個 dataclass 與一次方法呼叫，預期影響在微秒等級。仍需在場域主機實測：

1. 確認目前設定：`config/runtime_overrides.yaml` 優先於 `config/config.yaml`，記下 `reply_streaming.enabled` 的實際值（這次修改主要影響串流模式；舊有模式只影響帶網頁來源的回答）。
2. 基準：在主 checkout 切到合併前的 `layer-split`（或 `main`），重啟後端，關閉舞台 kiosk 頁面，在場域主機執行  
   `uv run --no-sync python scripts/measure_first_audio.py --rounds 5 --note "layer-split before 02" --output .scratch/first-audio-latency/02-before.json`
3. 修改後：切到含本工單的分支，重啟後端，同樣執行  
   `uv run --no-sync python scripts/measure_first_audio.py --rounds 5 --note "layer-split after 02" --output .scratch/first-audio-latency/02-after.json`
4. 比較兩份報告各類別（general、rag、handoff）的 `perceived_first_audio_seconds` 與 `first_audio_seconds`：P50 增加不超過 50 ms、P95 增加不超過 100 ms 即通過；並在舞台上確認免按對話、插話與字幕照常。

