<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 測試清理時發現的無呼叫者／範圍外程式碼
Status: resolved

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

### 2026-11-24 決定與處理

使用者確認五項都刪除，並要求一併清除目前版本沒有使用的模型程式碼與暫存：

- **刪除程式碼**：reply_streaming 的三個未接線類別（`channel.py` 只留 `PlayableFragment`）；
  `router.py` 只留 `ReplyMode`，並移除 `llm.response_router` 設定（舊檔中的這一段會被忽略）；
  舊 `<<<BOARD` 標記與 `answer_board.py`；LFM 2.5 thinking 路徑（llama-server 一律 `--reasoning off`）；
  UltraLight、ER-NeRF、TalkingGaussian 數位人引擎與它們的設定檔、安裝選項。
- **保留**：Wav2Lip。它在控制台可以選，所以補進 `current-version-baseline.json` 的可選能力；
  Matcha 也一併補上。
- **刪除模型檔**：`models/funasr/paraformer-zh`；`/home/oliver/llama` 中的 LFM2.5-2.6B、
  Qwen3.5-4B、Qwen3.8-27B GGUF；Ollama 的 `lfm2.5-thinking` 與三個 `qwen3.6`。
- **不動**：`~/.cache` 全域快取，以及 Ollama 的 `bge-m3`、`qwen3.5:4b`／`9b`、`nomic-embed-text`。

### 2026-11-24 追加：Wav2Lip 也移除

上面「保留 Wav2Lip」的決定被使用者推翻（不會再使用）。已刪除 `src/avatars/wav2lip/`、
`models/wav2lip256.pth`、`config/config_wav2lip.yaml`、控制台的引擎選項與畫質欄位、
`mouth_quality`／`schema`／`loader`／`builder`／`catalog`／`factory` 中的分支，以及相關測試；
`runtime_overrides.yaml` 裡舊的 `model.wav2lip` 區段會被忽略。MuseTalk 的 import、設定載入與場域
素材讀取已驗證不受影響。授權紀錄（`THIRD_PARTY_NOTICES.md`、`third_party/licenses/`、`NOTICE`）保留。

