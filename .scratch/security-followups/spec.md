<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 安全強化後續項目

Status: needs-triage

[安全強化與場域穩定性](../security-hardening/spec.md)（2026-10-29 合併）實作時刻意留下、
或在審查中發現但超出範圍的項目。每張 issue 獨立，可個別排程；信任邊界與審查規則沿用
[ADR 0021](../../docs/adr/0021-stage-local-console-login.md) 與
[CODING_STANDARDS.md](../../CODING_STANDARDS.md)。

| # | 項目 | 狀態 |
|---|---|---|
| 01 | 模型原始碼被 `models/` 規則排除於版控 | ready-for-human |
| 02 | 升級 Vite 8 清除剩餘 npm audit | ready-for-agent |
| 03 | CosyVoice 伺服器端點阻塞 event loop | ready-for-agent |
| 04 | 後端被 SIGKILL 時 llama-server 成孤兒 | ready-for-agent |
| 05 | RAGFlow 原始碼與附屬映像固定版本 | ready-for-agent |
| 06 | 控制台 Markdown 外部圖片可外洩資料 | ready-for-agent |
| 07 | 參考音訊回收桶還原與刪除檢查 | ready-for-agent |
| 08 | FunASR `model_size` 接受任意字串 | ready-for-agent |
| 09 | ER-NeRF／TalkingGaussian 不安全載入 | ready-for-agent |
