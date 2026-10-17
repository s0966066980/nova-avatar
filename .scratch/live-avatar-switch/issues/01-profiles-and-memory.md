<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 角色設定檔、遷移與記憶隔離
Status: resolved

根據[完整規格](../spec.md)建立獨立設定檔 ID、保存／套用及 revision、遷移現有有效設定、每會話／設定檔 LLM 記憶與 RAG 範圍隔離。完成 focused tests 才標示完成。

## Comments

2026-10-16：已實作 ProfileStore 一次性遷移、穩定 ID、revision 保存／套用、每會話／角色記憶與 RAG 範圍。測試涵蓋同素材不同設定檔、過期 revision、機密排除及選擇性記憶清除。

2026-10-17：完整回歸通過（581 passed、3 skipped），包含 12 項設定檔測試；設定檔與記憶隔離實作驗收完成。
