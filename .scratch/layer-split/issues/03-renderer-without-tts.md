<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 數位人渲染不再持有 TTS
Status: resolved
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

### 2026-11-26 實作完成（分支 `ls/03-renderer-without-tts`）

- **新的分工**：
  - TTS 層新增 `src/tts/audio_sink.py` 的 `AudioSink` 介面：`put_audio_frame`、`accepts_media`、`fragment_playback_committed`、`fragment_playback_ended`、`notify_fragment_synthesis_failed`、`observe_tts_onset_preroll_ms`、`observe_tts_retry`、`mark_stage_end`。`BaseTTS` 與各引擎的 `parent` 改名為 `sink`，`create_tts_engine(type, config, sink)` 不再認識 `BaseAvatar`。
  - 核心新增 `src/server/speaking_avatar.py` 的 `SpeakingAvatar`：以渲染器的 config 建立 TTS，並把自己當成 TTS 的 sink；PCM 原樣轉給 `renderer.put_audio_frame`（媒體序號、柵欄、直送音訊仍在渲染器內），片段事件轉給語音會話。`put_msg_txt`（清理文字、登記片段、送進 TTS）、`flush_talk`（先清 TTS 再清渲染器）、`render`（先啟動 TTS，再以同一個 `quit_event` 執行渲染器，結束或失敗時一律設定 `quit_event`）、`bind_profile`（清 TTS、換渲染器素材、換 TTS 的 config）都在這裡。
  - `state.avatar_streams` 存的是 `SpeakingAvatar`，由 `/offer` 的 `build_speaking_avatar` 在背景執行緒建立。其他核心程式照舊把它當成「這場對話的數位人」：未定義的屬性讀取轉給渲染器，`config` 與 `_role_presentation` 的寫入也寫到渲染器；`tts`、輪次快照等核心狀態留在 `SpeakingAvatar` 上。
  - 渲染器（`BaseAvatar`、`MuseTalkAvatar`）不再建立、啟動或清空 TTS，`configure_media_fence` 只剩 `media_guard`、`on_stale_drop`、`on_stage_end`。MuseTalk 等待不足 PCM 時改問 `has_pending_audio()`，由核心以 `configure_pending_audio(tts.has_pending_work)` 提供答案（200 ms 上限與判斷規則不變）。
  - `/humanaudio` 的音檔解碼（`put_audio_file`，含 300 秒上限）從渲染器搬到 `SpeakingAvatar`，程式碼原樣搬移，保留上游授權標示。
  - `RetryBudget` 搬到 `src/tts/retry.py`；`PlayableFragment` 先放在 `src/utils/playable_fragment.py`，envelope 型別改為只要求 `turn_id`、`generation`、`sequence` 的 Protocol，工單 07 再移到 `contracts/`。`ReplyCircuitBreaker` 是語音會話的熔斷（失敗後切回舊有模式），屬於輪次編排，留在核心；Edge 自己的熔斷（`edge_endpoint.note_failure`）原本就在 TTS 層。
- **例外清單**：刪除 03 的四條（`src.tts.engines.edge -> src.server.reply_streaming.channel`／`retry`、`src.avatars.base -> src.tts.factory`／`src.tts.base`），以及標為 06、因本工單而不再成立的兩條：`src.tts.base -> src.avatars.base`、`src.avatars.base -> src.vad.audio`。`tts-not-other-layers` 與 `avatar-not-other-layers` 已沒有任何例外。
- **保證**：音訊主時鐘、媒體序號、片段播放柵欄、嘴型連續控制、Matcha 預取的取消語意（`flush_talk` 清暫存並遞增 epoch、逐幀檢查 `accepts_media`）、Edge 的閘門 sink 與每輪重試預算、插話時丟棄舊輪次媒體，程式路徑都沒有改，只是 TTS 呼叫的對象從渲染器換成核心的 sink，sink 再轉給同一個渲染器方法。插話時清空順序維持「先 TTS、後渲染器」。
- **行為差異**：
  - 每個 20 ms 音框多一次 Python 方法轉呼叫（核心 sink → 渲染器），預期在微秒等級。
  - 換角色時 TTS 的 config 改在渲染器換完素材之後才設定（原本在素材鎖內）；換角色前已先清空 TTS，所以沒有進行中的合成會讀到它。
  - 渲染器結束或啟動失敗時，核心一律設定 `quit_event`，TTS 執行緒一定跟著停止（原本若在渲染器的 `try` 之前失敗，TTS 尚未啟動，現在則是先啟動再停止）。
  - `src.server.reply_streaming` 不再匯出 `PlayableFragment`、`RetryBudget`、`RetryPermit`（沒有使用者）。
- **測試**：新增 `tests/test_speaking_avatar.py`（14 項：核心以自己為 sink 建立 TTS、PCM 經核心到渲染器、文字清理與片段登記、片段事件轉給會話、沒有會話時的預設值、清空順序、TTS 與渲染器同生命週期、待播 PCM 查詢、換角色、渲染器狀態讀寫、`/humanaudio` 解碼與長度上限、渲染器不再建立 TTS、`/offer` 的組裝）。既有測試只調整建構方式：渲染器測試改用 `configure_pending_audio`、`parent=` 改為 `sink=`、`/humanaudio` 與錄影測試改經 `SpeakingAvatar`、WebRTC 生命週期測試把 `SpeakingAvatar` 換成原樣回傳的假物件、Edge 測試改從新位置 import；原本斷言渲染器清空 TTS 的檢查移到 `test_speaking_avatar.py` 的清空順序測試。TTS 引擎、Matcha 預取、播放柵欄、插話與舊媒體丟棄的斷言都沒有放寬。
- **驗證**：`uv lock --check`、`ruff check .`、`pyright`（0 errors）、`lint-imports`（7 kept）、`scripts/check-integration.py`、`pytest`（2224 passed、2 skipped；修改前 2210 passed、2 skipped）、`web` 的 lint／test（360 pass）／build 全部通過。

### 待維護者實機驗收：首音延遲與舞台聽感

1. 確認目前設定：`config/runtime_overrides.yaml` 優先於 `config/config.yaml`，記下 `reply_streaming.enabled`、`reply_streaming.decoupled_audio_clock` 與 `tts.type` 的實際值。
2. 首音延遲基準：在主 checkout 切到合併本工單前的 `layer-split`，`tts.type` 設為 `edgetts`，重啟後端，關閉舞台 kiosk 頁面，在場域主機執行  
   `uv run --no-sync python scripts/measure_first_audio.py --rounds 5 --note "layer-split before 03 edge" --output .scratch/first-audio-latency/03-before-edge.json`
3. 修改後：切到含本工單的分支，重啟後端，同樣執行  
   `uv run --no-sync python scripts/measure_first_audio.py --rounds 5 --note "layer-split after 03 edge" --output .scratch/first-audio-latency/03-after-edge.json`
4. 以 Matcha 聲線（設定檔選一個 Matcha 聲線模型）重複步驟 2、3，輸出檔名改成 `03-before-matcha.json`、`03-after-matcha.json`。
5. 比較各類別（general、rag、handoff）的 `perceived_first_audio_seconds` 與 `first_audio_seconds`：P50 增加不超過 50 ms、P95 增加不超過 100 ms 即通過。
6. 舞台聽感：重新開啟舞台頁面，分別以 Edge 與 Matcha 聲線問一題會切成三個以上片段的長回答（例如「請詳細介紹這個展區的三個重點」），確認嘴型與聲音同步、片段之間沒有跳音或疊音；回答途中插話一次，確認舊回答立刻停止、不再播出殘餘片段，新回答正常開始；再換一次角色（交接），確認新角色的聲音正確。
7. 若 Matcha 片段之間仍有空白，比對後端日誌的片段間隔（修正前 221–280 ms，預取後應約 20–50 ms）；若與修改前不同，回報並附日誌。
