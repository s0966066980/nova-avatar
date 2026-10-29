<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 第一句簡短的 Prompt 規則
Status: ready-for-agent
Blocked by: 04

依[規格](../spec.md)。第一個可播回覆片段需等完整句子（`src/server/reply_streaming/fragmenter.py`；逗號切分需 24 字以上且 0.5 s，0.5 s 只在新 token 到達時檢查）。

- 在回覆規則加入「以一句 15 字內的完整短句開頭」，不改完整語意邊界規則；以 E2B 驗證遵循率。
- 語意等待上限改為計時器觸發，不依賴新 token 到達。
- 量測第一個片段字數與時間；若仍不達標，在 Comments 提出放寬第一個片段邊界的方案（需改術語表與 ADR 0007，交使用者決定）。

## Comments
