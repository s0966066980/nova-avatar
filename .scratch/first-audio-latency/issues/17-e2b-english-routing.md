<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# E2B 英文交接路由
Status: ready-for-agent
Blocked by: 04

依[規格](../spec.md)「路由正確率明顯低於 9B 時，加關鍵字初篩，不回頭用 9B」。最終量測（`final-2026-10-30.json`，3 輪）交接 30 輪只成功 18 輪，失敗的 12 輪全是英文（en-01～04；en-02、en-04 是前一句未交接造成的連鎖）。9B 基準線 10/10。各次量測的英文交接失敗並不一致（`after-followups`：en-03/04；`ablation-a-only`：en-01/02；`offset-split`：全部）。

單句直接呼叫路由（E2B，2026-10-30 orchestrator 探測）：
- 「Will it rain in Taipei tomorrow?」→ specialist（正確）；但在量測工具的連續對話中常失敗。
- 「What is the weather forecast for Tainan this weekend?」→ clarify，`county` 空白：E2B 沒有把英文地名 Tainan 對應到「臺南市」。

- 以量測工具的交接序列（含前幾輪歷史）重現，找出英文交接失敗的實際原因（辨識文字、歷史、路由輸出、柵欄或取消）。
- 依規格加關鍵字初篩：中英文天氣用語與臺灣縣市名（含英文、拼音、常見別名）命中時直接判定交給天氣角色並填好縣市；未命中才交給 E2B。英文縣市名對應到正式中文名稱。
- 測試涵蓋中英文、別名、需要釐清鄉鎮的情況；實機以 `scripts/measure_first_audio.py` 確認交接 10/10（待實機驗證）。

## Comments
