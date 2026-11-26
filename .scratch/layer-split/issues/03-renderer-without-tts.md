<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 數位人渲染不再持有 TTS
Status: ready-for-agent
Blocked by: 01

依規格決定 13 與 ADR 0027。這是階段 0 風險最高的一張工單。

- 現況：
  - `src/avatars/base.py:162` 由 `BaseAvatar` 建立 TTS。
  - `BaseTTS`（`src/tts/base.py`）持有 `parent: BaseAvatar`，透過 `put_audio_frame`、`notify_fragment_synthesis_failed`、`fragment_playback_committed` 等方法回推音框與事件。
- 改法：
  - 由核心建立 TTS。
  - TTS 只依賴一個窄介面，例如 `AudioSink`：接收 PCM 幀與片段事件，並查詢片段是否已播完。核心實作這個介面，再轉交給渲染。
  - 數位人渲染對外只保留這些介面：`put_audio_frame(pcm, eventpoint)`、`flush`、`is_speaking`、片段播放事件，以及視訊幀與音框輸出。
- `src/tts/engines/edge.py` 使用的 `PlayableFragment`、`RetryBudget`：重試預算與熔斷移進 TTS 層；片段的資料型別先放在中立的位置，工單 07 再移到 `contracts/`。
- 必須保持不變的保證：音訊主時鐘、片段播放柵欄、嘴型連續控制、Matcha 片段預取的取消語意、插話時丟棄舊輪次的媒體（ADR 0007、0008）。
- 驗收：
  - 現有的 TTS、Matcha 預取、播放柵欄與插話測試全部通過；
  - 刪除對應的例外清單條目；
  - 首音延遲符合門檻；
  - 舞台實機以 Edge 和 Matcha 各對話一段多片段的長回覆，嘴型與聲音同步，沒有跳音。
