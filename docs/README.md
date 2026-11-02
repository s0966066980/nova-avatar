<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# Nova Avatar 文件索引（Jetson AGX Orin 版）

這份索引只涵蓋 `jetson-orin` 分支。專案總覽、安裝與啟動請先看根目錄的 [README](../README.md)。

## 先讀這些

| 文件 | 內容 |
| --- | --- |
| [architecture.md](architecture.md) | 系統架構、資料流、對話輪次與原始碼對照 |
| [models.md](models.md) | 使用的模型、本機可切換的模型與各自的授權依據 |
| [jetson-orin.md](jetson-orin.md) | Orin 的建置、CUDA 驗證、移植修正與驗證結果 |
| [../CONTEXT.md](../CONTEXT.md) | 專案詞彙表，文件與程式碼使用的共通語言 |

## 功能與操作

| 文件 | 內容 |
| --- | --- |
| [llm-reply-rules.md](llm-reply-rules.md) | 對話模型、助手角色與回覆規則 |
| [conversation-attachments.md](conversation-attachments.md) | 對話附件與舞台文字輸入 |
| [prerecorded-avatars.md](prerecorded-avatars.md) | 預錄數位人與說話素材製作 |
| [ragflow.md](ragflow.md) | RAGFlow 本機檢索整合 |
| [reports/ragflow-arm64.md](reports/ragflow-arm64.md) | 原生 ARM64 RAGFlow 建置與驗證報告 |

## 效能與診斷

| 文件 | 內容 |
| --- | --- |
| [realtime-avatar.md](realtime-avatar.md) | 數位人即時生成與 TensorRT UNet 診斷 |
| [fixed-read-aloud.md](fixed-read-aloud.md) | 固定文字朗讀與音畫同步 |
| [lfm-resolution.md](lfm-resolution.md) | LFM 與 720p／1080p 實測 |
| [avatar-performance.md](avatar-performance.md) | 播放效能實驗 |
| [reports/Nova-Avatar-Stutter-Causes-and-Fixes.pdf](reports/Nova-Avatar-Stutter-Causes-and-Fixes.pdf) | 卡頓成因與修正報告 |

## 專案狀態與維護

| 文件 | 內容 |
| --- | --- |
| [project-status.md](project-status.md) | 專案基線與歷史驗證結果（基準為 RTX 4090，非 Jetson） |
| [software-stack.md](software-stack.md) | 軟體組合、可選引擎與授權邊界 |
| [current-project-workflow.md](current-project-workflow.md) | 開新工作項目、驗證與交付流程 |
| [source-attribution-audit.md](source-attribution-audit.md) | 來源標註稽核 |
| [../THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) | 第三方聲明 |
| [agents/](agents/) | 給編碼代理的 issue tracker、triage 標籤與詞彙表使用規則 |

## 架構決策紀錄（ADR）

| 編號 | 決定 |
| --- | --- |
| [0001](adr/0001-push-avatar-speaking-state-over-webrtc.md) | 透過 WebRTC 主動推送數字人發話狀態 |
| [0002](adr/0002-server-side-streaming-silero-vad.md) | 由後端串流 Silero 判定使用者發話邊界 |
| [0003](adr/0003-server-owned-conversation-turns.md) | 由伺服器編排完整對話輪次 |
| [0004](adr/0004-do-not-retain-microphone-audio-by-default.md) | 預設不持久儲存麥克風音訊 |
| [0005](adr/0005-use-faster-whisper-for-stt.md) | 使用 faster-whisper 執行語音轉文字 |
| [0006](adr/0006-support-only-keyless-speech-engines.md) | 只支援不需外部憑證的語音引擎 |
| [0007](adr/0007-stream-replies-with-turn-isolation-and-audio-clock.md) | 以輪次隔離與音訊主時鐘串流數位人回覆 |
| [0008](adr/0008-use-visual-only-musetalk-mouth-continuity.md) | MuseTalk 段落邊界使用純視覺嘴型連續控制 |
| [0009](adr/0009-bounded-stage-caption-window.md) | 以完整可播回覆片段維持有界舞台字幕窗口 |
| [0010](adr/0010-console-rest-state-follows-turn-commit.md) | 控制台靜態紀錄以輪次提交的已播回覆為準 |
| [0011](adr/0011-separate-spoken-and-displayed-answer-commit.md) | 分開記錄已播語音與已顯示看板項目 |
| [0012](adr/0012-editable-rules-for-single-llm.md) | 以可編輯回覆規則指導單一 LLM |
| [0013](adr/0013-use-ragflow-for-retrieval-only.md) | 以獨立 RAGFlow 服務提供檢索，不接管回答 |
| [0014](adr/0014-compose-green-screen-avatars-on-server.md) | 在後端合成綠幕數位人與演播場景背景 |
| [0015](adr/0015-console-owned-assistant-profile.md) | 由控制台集中管理助手身分與 Prompt |
| [0016](adr/0016-separate-prerecorded-presentation-and-asset-production.md) | 將預錄呈現與說話素材製作分離 |
| [0017](adr/0017-session-owned-stage-language.md) | 各場舞台對話獨立擁有語系，控制台保存新對話預設 |
| [0018](adr/0018-session-owned-conversation-attachments.md) | 由各場對話持有分析附件 |
