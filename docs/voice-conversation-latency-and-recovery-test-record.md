<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 語音對話延遲與無效音訊恢復測試紀錄

日期：2026-09-15

## 範圍

本紀錄涵蓋 WebRTC 麥克風上行、Silero VAD、FunASR／Whisper、語音輸入品質閘門、
LLM 語意切片、TTS、MuseTalk 播放提交與下一輪收音恢復。此次問題的實際執行設定
為 FunASR、Edge TTS、MuseTalk 與串流回覆模式。

目前流程如下：

1. VAD 形成語音片段後關閉收音 gate，建立唯一的 `turn_id` 與 `turn_task`。
2. 品質閘門先檢查語音長度與 RMS；ASR 後再檢查空文字與可信度。
3. 無效音訊不產生使用者訊息、不呼叫 LLM、不寫入 history，也不讓數字人回覆。
4. 有效文字進入 LLM；完整句子立即送入 TTS，弱語意邊界最多等待設定值。
5. 下一個語音片段必須等前一片最後一個音訊影格完成，避免句子疊音。
6. 回答播放完成或無效音訊被丟棄後，伺服器釋放輪次並推送 `listening`，恢復收音。

## 根因與修正

### 無效音訊後麥克風失效

低可信或空白轉寫的提前返回路徑只清除了 `turn_id`，沒有清除已完成的
`turn_task`。收音 gate 要求兩者都為空，因此它持續停在 `paused`。修正後，丟棄
路徑會在同一個非同步任務內同時釋放兩者並立即刷新 gate。

回歸測試同時驗證：

- 咳嗽或低可信轉寫不會呼叫 LLM，也不會建立 `user_transcript`。
- `turn_id` 與 `turn_task` 都已釋放，最後狀態為 `listening`。
- 不重新建立會話，直接送入第二輪有效語音時，LLM 可正常收到新問題。

### 偶發首句等待過久

弱語意邊界原本最多等待 5 秒，且到期後仍略過既有子句，繼續等待下一個弱標點；
此值已高於既有首音 P95 的 2.5 秒整體 gate。現在預設等待上限為 0.5 秒；到期時
若緩衝區已有可獨立朗讀的子句，立即在該邊界釋放。完整句號仍會立即釋放，沒有
標點的短回答則在串流結束時送出，任何情況都不以字數在詞語中間硬切。

控制台仍可在 0.5 至 30 秒間調整。正式低延遲設定建議維持 0.5 秒；更高設定是
操作者明確接受首音延遲後的調校值。

## 沿用的驗收指標

正式基準環境為 RTX 4090、本機 llama.cpp、Edge TTS、MuseTalk、WebRTC 與單一
活躍會話。資料來源為
`.scratch/reply-voice-streaming/real-soak-mouth-continuity-50-rerun.json`。

| 指標 | 既有實測 | Gate | 本次判定 |
| --- | ---: | ---: | --- |
| 回合數 | 50 | 至少 50 | 沿用 |
| 首音 P50 | 1.185525 s | ≤ 1.2 s | 沿用；語意等待預設不超過 0.5 s |
| 首音 P95 | 1.691548 s | ≤ 2.5 s | 沿用；移除 5 s 預設等待 |
| A/V 偏差 P95 | 0.06 s | ≤ 0.08 s | 播放柵欄未放寬 |
| 插話停止 P95 | 0.000345 s | ≤ 0.2 s | 沿用 |
| 恢復收音 P95 | 0.301517 s | ≤ 0.5 s | 沿用；新增無效音訊立即恢復 |
| 最大媒體債務 | 0.24 s | ≤ 2 s | 音訊主時鐘未變更 |
| stale output | 0 | 必須為 0 | generation fence 未變更 |

0.5 秒語意等待是首音 P95 整體 gate 的 20%；5 秒則是該 gate 的 200%。這是設定
上限比較，不取代真實硬體的端到端量測。此次沒有改動 TTS 音訊 pacing、MuseTalk
推理或 WebRTC 時鐘。

## 2026-09-15 自動驗證結果

| 驗證 | 結果 |
| --- | --- |
| 無效音訊恢復、語意等待、播放提交、回覆協定與音訊時序 focused tests | 144 passed，12 subtests passed |
| Python 完整測試 | 399 passed，3 skipped |
| Web 測試 | 70 passed |
| Vite production build | passed；僅保留既有大 chunk 警告 |
| `scripts/check-integration.py` | passed；FunASR 與 MuseTalk 目前引擎依賴可匯入 |
| `git diff --check` | passed |

聚焦回歸測試位置：

- `tests/test_voice_session.py::VoiceTurnSessionTests::test_low_confidence_speech_transcript_never_reaches_llm`
- `tests/test_voice_session.py::VoiceTurnSessionTests::test_short_non_speech_reopens_listening_without_running_asr`
- `tests/test_reply_streaming.py::SemanticFragmenterTests::test_wait_expiry_releases_an_existing_clause_within_latency_budget`
- `tests/test_reply_streaming.py::BaselineReplayHarnessTests::test_real_soak_report_is_content_free_and_applies_all_slos`

## 實機複驗

本次自動驗證沿用已完成的 50 回合實機報告，沒有宣稱產生新的 RTX 4090 實機數據。
部署後若要更新正式基準，應使用相同 Edge TTS＋MuseTalk 單會話條件重跑至少 50
回合，並以本節所有 gate 判定；FunASR 的 ASR 階段耗時應同時從每輪
`stage_seconds.asr` 紀錄，避免把模型轉寫延遲誤判為語意切片延遲。
