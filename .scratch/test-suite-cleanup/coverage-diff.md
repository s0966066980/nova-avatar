<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 第二輪測試清理：覆蓋率前後比對

日期：2026-11-24。量測範圍為 `src/` 與 `scripts/`，使用 `-m "not live"`，並以
`--cov-context=test` 記錄每一行由哪些測試覆蓋。量測只是本次刪除的審查證據，不是 CI 門檻。

```bash
uv run --no-sync --with 'pytest-cov>=6' pytest -q -m "not live" \
  --cov=src --cov=scripts --cov-context=test --cov-report=
```

| | 清理前（`fe6e041`） | 清理後（`b740c72`） |
| --- | ---: | ---: |
| 主要回歸案例 | 2348 | 2232（另有 4 個 `live`） |
| 已覆蓋行數 | 26,086 | 24,624 |
| 耗時 | 約 3 分 15 秒 | 約 2 分 07 秒 |

## 減少的 1,462 行從哪裡來

- **1,474 行屬於已刪除的腳本**：`scripts/tts_bakeoff.py`（789 行）、`scripts/eval_llm_quality.py`（546 行）、`scripts/compare_asr.py`（139 行）。`tools/` 不在量測範圍內，所以 `repeated_syllables.py` 沒有列入。
- **新增覆蓋約 19 行**：主要來自改寫後的 Whisper 裝置選擇測試，該路徑原本完全沒有測試。
- **仍存在的程式中失去覆蓋的 7 行**，逐一列在下表。

| 位置 | 原本由誰覆蓋 | 判斷 |
| --- | --- | --- |
| `src/llm/engines/openai.py:231`：串流期間 provider 回報 usage、但本機端點的 context 容量尚未取得時，從快取補上容量 | 只有已刪除的 `test_llm_quality_eval.py`（透過它的假 llama.cpp 伺服器間接觸發） | **真實缺口，影響小**：只影響控制台顯示的 context 用量。需要的話可補一個直接測試 |
| `src/server/reply_streaming/fragmenter.py:43`：`_grapheme_spans("")` 回傳空串列 | 只有已刪除的 `test_llm_quality_eval.py` | 空字串的防護分支，可以接受 |
| `src/tts/engines/edge.py:821-825`：合成進行中收到 flush 時，取消目前與預取的工作 | 清理前由 `test_flush_talk_drops_prefetched_fragment_audio` **偶然**覆蓋；該測試沒有刪除 | **既有缺口，不是清理造成**：單獨連跑 6 次都沒有走到這幾行，只有剛好在全套負載下才會觸發。這個取消路徑目前沒有確定性的測試 |
