<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# E2B 英文交接路由
Status: resolved
Blocked by: 04

依[規格](../spec.md)「路由正確率明顯低於 9B 時，加關鍵字初篩，不回頭用 9B」。最終量測（`final-2026-10-30.json`，3 輪）交接 30 輪只成功 18 輪，失敗的 12 輪全是英文（en-01～04；en-02、en-04 是前一句未交接造成的連鎖）。9B 基準線 10/10。各次量測的英文交接失敗並不一致（`after-followups`：en-03/04；`ablation-a-only`：en-01/02；`offset-split`：全部）。

單句直接呼叫路由（E2B，2026-10-30 orchestrator 探測）：
- 「Will it rain in Taipei tomorrow?」→ specialist（正確）；但在量測工具的連續對話中常失敗。
- 「What is the weather forecast for Tainan this weekend?」→ clarify，`county` 空白：E2B 沒有把英文地名 Tainan 對應到「臺南市」。

- 以量測工具的交接序列（含前幾輪歷史）重現，找出英文交接失敗的實際原因（辨識文字、歷史、路由輸出、柵欄或取消）。
- 依規格加關鍵字初篩：中英文天氣用語與臺灣縣市名（含英文、拼音、常見別名）命中時直接判定交給天氣角色並填好縣市；未命中才交給 E2B。英文縣市名對應到正式中文名稱。
- 測試涵蓋中英文、別名、需要釐清鄉鎮的情況；實機以 `scripts/measure_first_audio.py` 確認交接 10/10（待實機驗證）。

## Comments

### 2026-10-30 根因（實作前）
- 量測紀錄 `logs/nova-avatar_2026-10-30_05-05-11.log`（final 量測）第 645、777 行：handoff-en-01／en-03 的 ASR 為 `language=en`、`status=completed`，`routing` 約 0.43 s 後 `llm_first_token=None`、首音約 0.8 s，也就是回了固定句而非交接；沒有取消、柵欄等待或辨識錯誤。量測工具不切換對話語言，整場 locale 都是 zh-TW。
- 以量測順序與累積歷史在 8080（E2B）重現（`scratchpad/e17/repro.py`、`single.py`）：
  1. 主角色歷史累積到路由取用的 10 則後，E2B 對 Taipei／Tainan 及臺中市等天氣問題回 `route=specialist`，但 `county` 空白（JSON 中出現換行漂移）。`coordinator.before_generate` 遇到 specialist 缺縣市，直接回固定句「請問您想查詢哪個縣市的天氣？」，因此沒有交接。歷史較短時（4～8 則）同一問題能填好縣市。
  2. 「Tainan」不管歷史長短，E2B 都輸出 `county="臺南"`（少了「市」），不在 `COUNTIES` 中，`route_question` 因此改成 clarify。
  3. en-02、en-04 是連鎖失敗：前一句沒有交接，訪客仍在主角色，「回到主角色」這次交接自然不會發生。
- 結論：問題出在 E2B 的縣市欄位輸出，不是辨識文字、歷史清除、柵欄或取消。中文能成功，是因為縣市名可以從問題原文照抄；英文則需要翻譯對照。

### 2026-10-30 實作
- 新增 `src/profiles/weather_keywords.py`：一張 `PLACES` 表列出 22 個縣市的中文、英文、拼音與常見別名（含 臺北縣→新北市、馬祖→連江縣；台→臺 自動正規化）。同一名稱列在兩個縣市底下（新竹、嘉義、Hsinchu、Chiayi）時視為不明確。另有天氣用語、日期詞、此刻詞與第二主題詞的資料表。
- `keyword_route` 只在以下情況直接判定 `specialist` 並填好縣市：只有一句、命中天氣用語、正好一個不歧義的縣市，而且沒有鄉鎮區、第二主題或無法解析的日期（下週三、11/3、next Monday）。日期詞會解析成今天／明天／後天／大後天／週末，「現在／right now」解析成 `current`。鄉鎮只沿用同縣市的已確認地點或場域預設地點。其他情況一律交給 E2B，所以只提到城市的非天氣問題（fun fact、溫泉、彩虹眷村、公司服務）不會觸發。
- `route_question`：專門角色有 weather 工具時，先跑初篩，命中就不呼叫模型。模型路徑也一併補強：模型輸出的縣市以同一張表正規化（「臺南」→「臺南市」）；模型留空、而訪客只說了一個縣市時，自動補上該縣市。`language.py` 原本的英文別名表併入新表；`explicit_counties` 遇到不明確名稱會回傳所有可能的縣市，原本 `explicit_english_counties` 的測試也移到 `tests/test_weather_keywords.py`。
- `tests/test_llm_quality_eval.py`：30 題中 w01、w06、h01、h02 改由初篩判定（皆正確），因此假模型的路由正確率預期由 19/30 改為 23/30。
- 驗證：新測試 63 項；完整測試 1363 passed（只剩 2 個已知的 worktree 基準失敗）；ruff、pyright、check-integration 皆通過。以量測順序在 8080 重放兩輪（`scratchpad/e17/repro.py`），交接 10/10，英文兩題的縣市為 臺北市、臺南市。

### 待實機驗證
1. 讓 8010 跑本分支（或合併後的 `first-audio-latency`），維持 E2B 設定。
2. `scripts/measure_first_audio.py`（照 final 量測參數，3 輪）→ 預期 handoff 30/30 `handoff_observed=true`，且 en-01、en-03 有 `specialist_first_audio_seconds`。
3. 預期交接輪的 `routing` 階段在初篩命中時接近 0 s。

### 2026-10-30 實機驗證（orchestrator）
`final-validation-2026-10-30.json`（整合分支 8479114，3 輪）：交接 30／30 實際交接（修正前 18／30）；交接輪次感知首音 P50／P95 1.20／1.94 s。
