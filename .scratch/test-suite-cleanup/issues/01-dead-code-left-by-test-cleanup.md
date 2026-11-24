<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 測試清理時發現的無呼叫者／範圍外程式碼
Status: needs-triage

2026-11-24 的 pytest 清理只處理測試；以下正式程式碼在清理過程中發現沒有呼叫者，
或不在[目前版本範圍](../../../docs/current-version-testing.md)內。清理時遵守「測試跟著程式碼走」：
程式碼還在，就保留它現有的測試；程式碼刪除時，測試一併刪除。

| 項目 | 位置 | 現況 | 現有測試 |
| --- | --- | --- | --- |
| 回覆串流的未接線元件 | `src/server/reply_streaming/` 的 `MediaDebtBudget`、`BoundedFragmentChannel`、`ReplyFragmentProducer` | `src/`、`scripts/` 中除了 `__init__.py` 的匯出之外沒有任何呼叫者 | `tests/test_reply_streaming.py` 的對應類別（5 案例） |
| 舊關鍵字路由 | `src/llm/router.py` 的 `RuleRouter`、`LLMFallbackClassifier`、`ReplyRouter` | ADR-0012 已改為單一模型協定；`src/` 只再匯入同檔的 `ReplyMode` | 無（`tests/test_llm_router.py` 已於上一輪刪除） |
| 舊 `<<<BOARD` 看板標記 | `src/llm/answer_board.py`、`src/llm/base.py` 的 legacy 分支 | 只有模型自行輸出舊標記時才會觸發；現行 prompt 不再要求這種標記 | `tests/test_answer_board.py` |
| LFM 2.5 thinking 路徑 | `src/llm/llamacpp_protocol.py`、`src/llm/llamacpp.py:532` 附近、`src/llm/engines/openai.py` | 不在本版模型範圍；上一輪已刪除測試，但程式碼還在 | 無 |
| UltraLight 數位人 | `src/avatars/ultralight/`、`src/avatars/factory.py`、`src/avatars/catalog.py` | 不在 README 與本版範圍表中，但工廠與目錄仍有分支 | `tests/test_render_stop.py` 的 UltraLight 案例 |

## 需人決定

1. 有沒有場域或既有設定檔仍在使用 UltraLight 或 LFM 2.5？如果有，應列入本版範圍並補測試，而不是刪除。
2. 其餘三項確認沒有用途後，刪除程式碼和對應的測試，並重跑 `scripts/check-integration.py`（`answer_board`、`router` 可能有上游來源聲明）。

## Comments
