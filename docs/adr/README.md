<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 架構決策紀錄（ADR）

每份 ADR 記錄一個已做出的設計決定與取捨。新的決定請用下一個編號新增；被取代的 ADR 保留原檔，並在 `status:` 標明取代者。

各 ADR 內提到的規格、工單與驗證紀錄（原在 `.scratch/`）已不在 repo 內；`.scratch/` 現為本機、不進 git。要查閱請用 `git show b2b610b:.scratch/<路徑>`。

| 編號 | 標題 | 狀態 |
| --- | --- | --- |
| 0001 | [透過 WebRTC 主動推送數字人發話狀態](0001-push-avatar-speaking-state-over-webrtc.md) | accepted |
| 0002 | [由後端串流 Silero 判定使用者發話邊界](0002-server-side-streaming-silero-vad.md) | accepted |
| 0003 | [由伺服器編排完整對話輪次](0003-server-owned-conversation-turns.md) | accepted |
| 0004 | [預設不持久儲存麥克風音訊](0004-do-not-retain-microphone-audio-by-default.md) | accepted |
| 0005 | [使用 faster-whisper 執行語音轉文字](0005-use-faster-whisper-for-stt.md) | accepted |
| 0006 | [只支援不需外部憑證的語音引擎](0006-support-only-keyless-speech-engines.md) | accepted |
| 0007 | [以輪次隔離與音訊主時鐘串流數位人回覆](0007-stream-replies-with-turn-isolation-and-audio-clock.md) | accepted |
| 0008 | [MuseTalk 段落邊界使用純視覺嘴型連續控制](0008-use-visual-only-musetalk-mouth-continuity.md) | accepted |
| 0009 | [以完整可播回覆片段維持有界舞台字幕窗口](0009-bounded-stage-caption-window.md) | accepted |
| 0010 | [控制台靜態紀錄以輪次提交的已播回覆為準](0010-console-rest-state-follows-turn-commit.md) | accepted |
| 0011 | [分開記錄已播語音與已顯示看板項目](0011-separate-spoken-and-displayed-answer-commit.md) | accepted |
| 0012 | [以可編輯回覆規則指導單一 LLM](0012-editable-rules-for-single-llm.md) | accepted |
| 0013 | [以獨立 RAGFlow 服務提供檢索，不接管回答](0013-use-ragflow-for-retrieval-only.md) | accepted |
| 0014 | [在後端合成綠幕數位人與演播場景背景](0014-compose-green-screen-avatars-on-server.md) | accepted |
| 0015 | [由控制台集中管理助手身分與 Prompt](0015-console-owned-assistant-profile.md) | accepted |
| 0016 | [以數位人設定檔隔離角色設定與訪客記憶](0016-isolate-avatar-profiles-and-visitor-memory.md) | accepted |
| 0017 | [以單一輸入來源協調共用角色交接](0017-coordinate-avatar-handoffs-with-one-input-owner.md) | superseded by ADR-0020 |
| 0018 | [將閒置招呼與訪客提問分開編排](0018-separate-idle-greetings-from-visitor-turns.md) | accepted |
| 0019 | [以對話保存語系與附件，保留角色記憶隔離](0019-keep-conversation-state-across-role-handoffs.md) | accepted |
| 0020 | [讓控制台與舞台各自持有對話與角色](0020-independent-console-and-stage-conversations.md) | accepted |
| 0021 | [舞台僅限本機，控制台需管理者登入](0021-stage-local-console-login.md) | accepted |
| 0022 | [路由、檢索與主回答並行，路由判定後才放行播放](0022-run-routing-retrieval-and-answer-concurrently.md) | accepted |
| 0023 | [當次角色組合改為一主多專、任意角色直接交接](0023-role-composition-with-any-to-any-handoff.md) | accepted |
| 0024 | [由後端控制有上限的網頁搜尋，再交給目前模型回答](0024-bounded-web-search-before-answer.md) | accepted |
| 0025 | [Matcha 聲線模型作為可選 TTS 引擎，不以 Edge 輸出蒸餾](0025-matcha-voice-models-without-edge-distillation.md) | accepted |
| 0026 | [Edge 只作為 Matcha 訓練的測試用老師](0026-edge-as-test-only-matcha-teacher.md) | accepted |
| 0027 | [依處理層劃分程式；STT、LLM、TTS 以 loopback 服務為目標，Avatar 留在核心行程](0027-split-code-by-processing-layer.md) | accepted |
| 0028 | [維持單一 repo，各處理層各自宣告依賴，`contracts/` 是跨層契約的唯一來源](0028-monorepo-with-contracts-package.md) | accepted |
