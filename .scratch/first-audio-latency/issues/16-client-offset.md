<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 發話結束判定與用戶端偏移
Status: resolved
Blocked by: 01

依[規格](../spec.md)。E2B 切換後（`after-e2b-2026-10-30.json`）一般輪次感知首音延遲 P50 2.03 s，其中約 0.71 s 不在伺服器各階段內：`vad_endpoint` 固定 0.32 s，用戶端偏移（感知 − 伺服器估算）P50 0.39 s、P95 0.50 s。第一階段目標 1.2 s 下，這兩段就占六成。

- 拆解用戶端偏移：量測工具送出麥克風音訊的緩衝、伺服器收到最後人聲幀的時間、Silero VAD 在人聲結束後機率下降所需的拖尾、`vad_endpoint` 的實際意義（設定值或量測值）、回覆音訊從送出到用戶端解碼（aiortc 抖動緩衝）。為缺少的時間點補指標，讓偏移可以拆成各段。
- 區分量測工具本身造成的延遲與真實瀏覽器會遇到的延遲；必要時修正工具，讓感知首音延遲反映舞台瀏覽器。
- 對可調整的部分（靜音等待長度、VAD 門檻、抖動緩衝）列出選項、可省時間與風險（例如句中停頓被誤判為說完），交使用者決定，不自行改預設。

## Comments

### 2026-10-30 實作（分支 `fal/16-client-offset`）

**偏移的組成（離線實驗＋E2B 實測對照）**。E2B 一般輪次用戶端偏移 P50 0.39 s：

| 段 | 估計 | 依據 | 舞台瀏覽器也有？ |
|---|---|---|---|
| Silero 拖尾（人聲低於 −40 dBFS 後仍判為語音） | P50 0.08、P95 0.18 s | 32 句 fixture 經 Opus 來回、CPU Silero、門檻 0.5 | 有 |
| 上行（工具送出 → 伺服器收到） | 約 0.10 s，其中 0.08 s 是伺服器端 aiortc 抖動緩衝（prefetch 4 × 20 ms） | 兩個本機 aiortc peer 迴路，不經 Nova 伺服器 | 有，伺服器端同樣是 aiortc |
| 可聽起音（伺服器送出第一個非零幀 → 第一個可聽幀） | 0.10–0.14 s | Edge TTS 修剪器保留最多 160 ms 低能量前導（`MAX_PREROLL_SECONDS`） | 有，使用者這段聽不到 |
| 下行（伺服器送出 → 工具收到） | 約 0.10 s，其中 0.08 s 是工具端 aiortc 抖動緩衝 | 同一個迴路實驗 | 沒有，量測工具專屬 |

四段合計 P50 約 0.38 s。實測偏移範圍 0.35–0.51 s，也符合「約 0.30 s 固定段＋0.04–0.21 s 拖尾」。`vad_endpoint` 是**設定值**：音訊時間軸上的靜音幀數 × 32 ms，`ceil(300/32)=10` 幀，所以固定是 0.32 s，不是量測到的牆鐘時間。從人聲實際結束到判定說完，實際約為 拖尾 0.08＋0.32＋上行 0.10 ≈ 0.50 s。

**補上的指標（`turn_metrics`）**
- `vad_speech_tail`：在伺服器收到的音訊上，從最後一個 −40 dBFS 幀到靜音計數開始（`SpeechSegment.speech_tail_ms`）。以同一批 fixture 驗證，與離線量測的差距在 ±16 ms 內（20／32 ms 格點），只有 1 句差 96 ms。
- `vad_processing`：收到完成端點的上行幀 → 判定說完（重取樣＋VAD 執行緒）。
- `webrtc_audible_onset`：第一個非零回覆幀 → 第一個峰值 > 64 的幀。WebRTC 送出軌回報每幀峰值。
- `clock_marks`：`speech_end`、`first_audio`、`first_audible` 的單調時鐘原始值。量測工具與後端同主機，共用 `time.monotonic`。

**量測工具（報告 schema 2）**
- 每輪新增 `offset_split`（`vad_speech_tail`＋`vad_processing`＋`uplink`＋`audible_onset`＋`downlink`），加總等於 `client_offset_seconds`。
- `perceived_first_audio_seconds` 改為「人聲結束 → 伺服器送出第一個可聽幀」（`perceived_basis=server_send`），依術語表的「送出」定義，不含工具專屬的下行。下次實測數值預期比舊報告低約 0.10 s。
- 舊定義保留為 `client_received_first_audio_seconds`。對齊檢查仍用舊定義，所以 `client_offset_seconds` 可以和舊報告比較。
- 伺服器沒有時鐘標記，或時鐘對不上（端點不在人聲結束後 0–5 s 內）時，退回 `client_receive`。
- 伺服器端 `first_audio_seconds` 未改：它在不可聽的前導幀就計時，會比可聽起音早約 0.1 s，差值看 `audible_onset`。
- 工具上行與瀏覽器的差異（瀏覽器擷取緩衝與音訊處理，約 10–20 ms）無法離線量測，沒有計入。

**可調整項（交使用者決定，預設未改）**

| 選項 | 可省 | 風險 |
|---|---|---|
| `min_silence_ms` 300 → 288（9 幀；原意 300 ms，實際等 320 ms） | 0.03 s | 幾乎沒有 |
| `min_silence_ms` → 250／200／160（8／7／5 幀） | 0.06／0.10／0.16 s | 句中停頓被當成說完，問題被截斷。fixture 是單句 TTS，句中沒有停頓，無法評估，需真人錄音或現場試用 |
| VAD 門檻 0.5 → 0.7 | 拖尾 P50 只少約 0.01 s，P95 不變 | 小聲或遠距語音漏判，不建議 |
| 伺服器接收端 aiortc 抖動緩衝 prefetch 4 → 1（只套用在舞台 loopback peer） | 上行約 0.06 s（迴路實測 98 → 37 ms） | 要 patch aiortc 內部，升級可能失效；在有抖動的網路（遠端控制台 Wi‑Fi）會掉封包或破音，影響辨識 |
| Edge TTS 前導上限 0.16 s → 0.04 s | 最多約 0.1 s | 可能切掉輕聲字首。改用 BreezyVoice（issue 09／10）後要重量 `audible_onset` |
| 預判端點：靜音 160 ms 就先跑辨識與路由，320 ms 才確認，恢復說話就取消 | 最多 0.16 s，不會截斷問題 | GPU 白算與實作複雜度，需新 ADR |
| 下行抖動緩衝 | 不需調整 | 只影響量測工具，已排除在感知首音延遲之外 |

**驗證**：`tests/test_first_audio_latency.py` 新增 12 項（共 43 項）；`tests/test_vad.py` 新增 3 項。全套 1279 passed，只有 2 項已知 worktree 基準失敗。另把 3 個測試假播放器的 `notify_audio_activity` 改成新簽名（多一個 `peak`）。ruff、pyright、`check-integration.py` 都通過。離線腳本與結果（未進版控）：`/tmp/claude-1000/-home-oliver-nova-avatar/f284899e-3e7d-40e8-bf07-77d0ecc09394/scratchpad/fal16/vad_tail.py`、`/tmp/claude-1000/-home-oliver-nova-avatar/f284899e-3e7d-40e8-bf07-77d0ecc09394/scratchpad/fal16/rtc_loopback.py`（結果在同目錄的 `vad_tail.json`、`rtc_loopback.json`）。

### 待實機驗證

1. 用含本分支的整合程式碼重啟後端（舊程式碼沒有 `clock_marks`，量測工具會退回 `client_receive`）。關閉 kiosk 舞台頁。
2. 在舞台主機執行：
   ```
   cd /home/oliver/nova-avatar
   .venv/bin/python scripts/measure_first_audio.py --rounds 1 --warmup 1 \
     --note "fal/16 offset split; E2B; whisper zh/en; edge-tts" \
     --output .scratch/first-audio-latency/offset-split-2026-10-30.json
   ```
3. 預期結果：
   - 每輪印出 `(server_send)` 與 `offset_split`。
   - 一般輪次 P50：`vad_speech_tail` 約 0.08、`vad_processing` ≤ 0.01、`uplink` 約 0.10、`audible_onset` 約 0.10、`downlink` 約 0.10 s。
   - `client_received_first_audio_seconds` 與 E2B 報告的感知值同量級（約 2.0 s）。
   - `perceived_first_audio_seconds` 約低 0.10 s。
   - 若 `uplink` 明顯大於 0.12 s，代表伺服器上行處理有積壓，再查 `_consume_track`。
4. 選做：在舞台 Chrome 開 `chrome://webrtc-internals`，讀音訊 inbound-rtp 的 `jitterBufferDelay / jitterBufferEmittedCount`，作為瀏覽器下行的參考值（不計入感知首音延遲）。
5. 把各段 P50／P95 摘要補在這裡，再設 `Status: resolved`。

### 2026-10-30 實機拆解（orchestrator）
`offset-split-2026-10-30.json`（整合分支 3f7dc45，E2B、中英偵測、檢索上限 0.7 s、Edge TTS，32 輪全對齊）：
- 用戶端偏移 P50 0.388 s ＝ Silero 拖尾 0.076＋上行 0.092＋VAD 處理 0.003＋Edge 開頭無聲段 0.100＋下行（量測工具專有）0.103 s，與離線估計一致。
- 依新定義（伺服器送出第一個可聽幀）感知首音延遲 P50／P95：一般 1.99／2.22 s、RAG 2.05／2.17 s、交接 1.57／1.92 s；舊定義（用戶端收到）一般 2.12 s。
- 一般輪次 P50 組成：拖尾 0.07＋靜音等待 0.32＋上行 0.09＋辨識 0.08＋檢索等待 0.57＋首片段 0.43＋片段到送出 0.36＋可聽起點 0.10 s。
可再節省的選項（靜音等待、抖動緩衝、Edge 開頭無聲段、推測式端點）列於上方，交使用者決定，預設未變。
