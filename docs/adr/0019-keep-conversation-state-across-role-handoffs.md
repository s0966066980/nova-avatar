<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

---
status: accepted
---

# 以對話保存語系與附件，保留角色記憶隔離

Jetson 的語系與附件原本以單一角色的獨立場次運作，直接移植會讓 PC 角色交接
後改回角色預設語言，或遺失訪客已提供的文件。因此訪客／控制台測試對話各自
持有語系、附件與選取狀態，角色交接沿用它們；各角色使用自己對應語言的聲音，
歷史與知識範圍仍依角色隔離，不因附件可共用而合併完整角色歷史。

保留 [ADR-0016](0016-isolate-avatar-profiles-and-visitor-memory.md) 的角色身分與
記憶邊界，以及 [ADR-0017](0017-coordinate-avatar-handoffs-with-one-input-owner.md)
的單一輸入來源與同步展示。替代方案是語系完全隨角色設定切換，或所有角色
共用完整對話歷史；前者破壞訪客整場語言的一致性，後者混用身分與知識範圍。
不具附件視覺能力的角色必須明確拒絕相關處理，不能以一般文字回答冒充文件分析。

此為 2026-10-28 訪談 Q5–Q7 已接受並完成移植的設計；詳細行為見
[移植規格](../../.scratch/jetson-to-pc-port/spec.md)，自動化結果及實機限制見
[PC 移植驗證](../../.scratch/jetson-to-pc-port/validation/README.md)。

## 2026-10-29：修訂兩端關係

[ADR-0020](0020-independent-console-and-stage-conversations.md) 取代本文件沿用的
單一輸入來源與同步展示；語系、附件與各角色記憶的歸屬繼續適用於各自的
控制台對話及舞台對話。
