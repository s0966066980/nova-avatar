<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 數位人渲染不再持有 TTS
Status: ready-for-human
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

## Comments

- 2026-11-27：程式與測試已完成；實機驗收與延遲量測待人工。
  - 渲染層不再 import TTS：`BaseAvatar.__init__` 與 `create_avatar` 改為接收核心提供的 `speech_factory`（`src/avatars/speech.py` 定義 `SpeechSource`／`SpeechFactory`）；核心的 `src/server/speech.py` 的 `tts_speech_factory` 由 `routes/webrtc.py` 傳入。
  - TTS 不再 import 渲染層：`BaseTTS` 只依賴 `AudioSink`（`src/tts/audio_sink.py`，只有 `put_audio_frame` 必備，其餘事件由引擎以 `getattr` 取用，維持原行為）。
  - `PlayableFragment`、`RetryBudget`／`RetryPermit` 移進 TTS 層（`src/tts/fragment.py`、`src/tts/retry.py`）；`TurnEnvelope` 移到中立的 `src/utils/turn_envelope.py`（`turn.py` 重新匯出）；`sanitize_speech_text` 移到 `src/utils/speech_text.py`（`src.tts.base` 重新匯出）。
  - 已刪除 5 條例外：`avatars.base -> tts.base`、`avatars.base -> tts.factory`、`tts.base -> avatars.base`、`tts.engines.edge -> ...channel`、`...retry`。
- 與工單原文的差異：渲染層仍持有注入進來的說話來源（`avatar.tts`），文字佇列、`flush_talk`、`has_pending_work` 與音框推送都照舊經由頭像。原因是 `avatar.tts` 被控制台設定、角色交接、MuseTalk 的說話狀態判斷與數十個測試直接使用；把「核心直接送文字給 TTS、再把 PCM 轉交渲染」整個反轉，需要同時改動輪次、插話與播放柵欄，風險太高又無法在這裡實機驗證。目前的做法已讓兩層互不 import，也讓 07 可以把 `SpeechSource` 與 `AudioSink` 升級成 `contracts/` 裡的 Protocol。若要完整反轉，建議另開工單。
- `TTS` 的 `parent` 屬性名稱保留（型別改為 `AudioSink`），避免大量測試改名。
- 待人工：
  1. 舞台實機以 Edge 和 Matcha 各對話一段多片段長回覆，確認嘴型與聲音同步、沒有跳音；
  2. 以 `scripts/measure_first_audio.py` 量測首音延遲（P50 增加不超過 50 ms、P95 不超過 100 ms）。
