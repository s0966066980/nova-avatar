<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 文件索引

這裡只放持續維護的文件。一次性的規格、工單與量測輸出放在本機的 `.scratch/`（不進 git）；
交付後留下的決定寫成 [ADR](adr/README.md)。根目錄的 [README](../README.md)、
[CONTEXT](../CONTEXT.md)、[CODING_STANDARDS](../CODING_STANDARDS.md)、[AGENTS](../AGENTS.md)、
[NOTICE](../NOTICE) 與 [THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md) 維持在根目錄。

## guides/：安裝與操作

| 文件 | 讀者 | 內容 |
| --- | --- | --- |
| [installation.md](guides/installation.md) | 部署人員 | Linux x86_64 完整安裝流程、TensorRT |
| [x86-performance.md](guides/x86-performance.md) | 部署人員 | x86 影音排程與效能優化、可選的 TensorRT 與輸出尺寸 |
| [ragflow.md](guides/ragflow.md) | 部署人員 | RAGFlow 本機檢索整合 |
| [voice-models.md](guides/voice-models.md) | 操作人員 | Matcha 聲線模型安裝、訓練、刪除與授權標示 |
| [idle-greetings.md](guides/idle-greetings.md) | 操作人員 | 閒置招呼 |
| [conversation-attachments.md](guides/conversation-attachments.md) | 操作人員 | 對話附件與舞台文字輸入 |

## project/：專案狀態與流程

| 文件 | 讀者 | 內容 |
| --- | --- | --- |
| [project-status.md](project/project-status.md) | 維護者 | 目前已交付能力與可重現的驗證結果、首音延遲實測 |
| [current-project-workflow.md](project/current-project-workflow.md) | 維護者、agent | 新工作項目、驗證、清除過往項目與發行交接 |
| [current-version-testing.md](project/current-version-testing.md) | 維護者 | 目前版本的主要測試基準 |
| [software-stack.md](project/software-stack.md) | 維護者、法務 | 可選引擎與各自的散布邊界、商業審查設定檔 |
| [source-attribution-audit.md](project/source-attribution-audit.md) | 維護者、法務 | 各原始碼根目錄的來源歸屬分類 |

## adr/ 與 agents/

- [adr/](adr/README.md)：28 份架構決策紀錄與索引。
- [agents/](agents/)：給 agent 的導航、issue 追蹤、分類標籤與領域文件（保留英文標題）。

## 各層文件

[contracts](../contracts/README.md) ·
[core](../core/README.md) ·
[services/stt](../services/stt/README.md) ·
[services/llm](../services/llm/README.md) ·
[services/tts](../services/tts/README.md) ·
[avatar](../avatar/README.md) ·
[tests](../tests/README.md)
