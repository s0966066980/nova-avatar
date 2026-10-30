# 目前專案基線

更新日期：2026-10-30

此文件記錄 Nova Avatar 目前已交付能力、可重現的驗證結果與執行邊界。
新的工作項目、舊實驗的清理與 release handoff 流程請依
[`current-project-workflow.md`](current-project-workflow.md)；可選引擎與商業審查
邊界請依 [`software-stack.md`](software-stack.md)；設計決定見 [`adr/`](adr/)。

## 已完成範圍

| 領域 | v1 已完成能力 |
| --- | --- |
| 對話與傳輸 | WebRTC 雙向音訊、Avatar 影像、事件通道、免按對話、按住說話、插話、斷線清理與伺服器擁有的單一有效輪次 |
| 語音輸入 | Silero 服務端端點偵測（說完判定靜音 192 ms，6 個 32 ms 幀，約 0.2 s）、faster-whisper small（預設，語音輪次只在中英文間自動偵測、beam 1、記憶體直傳）／FunASR（可選，僅中文）、繁體轉換、STT 預熱、無效音訊品質閘門與執行期設定 |
| 回覆生成 | llama.cpp（預設 Gemma 4 E2B 全 GPU，Qwen3.5-9B 可選；放不下全部層數即啟動失敗並說明）／Ollama、路由與檢索和主回答並行、串流 token、交易式 history、柔性回覆長度、單一 LLM 可編輯回覆規則、控制台集中管理的助手身分與 Prompt |
| 知識庫檢索 | 可選的本機 RAGFlow 檢索：依數位人選擇知識庫、控制台測試檢索、BGE-M3 嵌入（llama.cpp，CPU）；見 [`ragflow.md`](ragflow.md) |
| 看板回答 | SIMPLE／BOARD 協定、口語摘要與看板項目分流、顯示確認、已顯示項目上下文與輪次隔離 |
| 語音與字幕 | 多 TTS adapter（Edge TTS 為執行預設但僅供開發；BreezyVoice 本機台灣華語已整合）、可靠語意切片（每輪第一個片段可在 8 字以上的子句處提早釋放）、播放提交、字幕顯示窗口；字幕在播放結束或輪次提交後才淡出 |
| 數字人 | MuseTalk（Supported / Commercial）、Wav2Lip（Research / Non-commercial）、Ultralight、ER-NeRF、TalkingGaussian；MuseTalk 段落連續、待機相位匹配與 4–6 影格回答收尾 settling |
| 演播場景 | MuseTalk 綠幕數位人於後端色鍵合成至共用背景（圖片、GIF、循環影片），講話中可切換背景；角色與背景可封存／復原 |
| 設定與生命週期 | LLM、Avatar、VAD、STT、TTS、Prompt、Rule、回覆模式、知識庫與舞台設定；owned llama-server 正常關閉清理 |
| 控制台驗證 | 自訂 Prompt 的一鍵真實語音鏈路測試、逐階段延遲與既有 SLO Gate、環境快照、實際播放回覆及本機持久歷史 |
| 安全與隱私 | generation fence、取消後拒絕 stale output、有界媒體背壓；未啟動錄製時不持久保存原始麥克風音訊 |

## 首音延遲實測（2026-10-30）

取代 9 月的 1.19 s 基準。那次從「伺服器接受 Prompt」起算，沒有角色路由與 RAG
檢索，不含靜音等待與辨識，不代表語音輪次的實際等待。規格與逐項決定見
[首音延遲改善規格](../.scratch/first-audio-latency/spec.md)。

### 量測方式與起訖點

工具 `scripts/measure_first_audio.py` 以舞台身分（loopback）建立真實 WebRTC，
即時送出記憶體內合成的固定語句（一般 11、RAG 11、交接 10，中英文皆有；
不存音訊），合併伺服器的 `turn_metrics`。

| 指標 | 起點 | 終點 |
| --- | --- | --- |
| **感知首音延遲**（達標判定用） | 錄音中人聲實際結束 | 伺服器送出該輪第一個可聽（峰值 > 64）WebRTC 回覆音訊幀；工具與後端同主機，以共用單調時鐘比對（`perceived_basis=server_send`） |
| 用戶端收到 | 錄音中人聲實際結束 | 量測工具（aiortc）收到第一個可聽回覆音訊幀；比上一列多約 0.10 s 下行與工具端抖動緩衝，舞台瀏覽器不同 |
| 首音延遲 | VAD 判定說完 | 伺服器送出第一個非靜音回覆音訊幀 |
| 伺服器接受 Prompt 起算 | 辨識結果進入回覆流程 | 同上 |

基準線量測時伺服器還沒有時鐘標記，它的感知值是「用戶端收到」定義；與基準線
比較時請看同一定義的欄位。

- **基準線**：`.scratch/first-audio-latency/baseline-2026-10-30.json`。`main`＋量測
  指標，Qwen3.5-9B 全 GPU、Whisper small（auto、beam 5）、路由與檢索串行、
  Edge TTS；1 輪 32 句。
- **最終**：`.scratch/first-audio-latency/final-validation-2026-10-30.json`（整合分支
  `8479114`，含 code review 修正與天氣關鍵字初篩；修正前的 `final-2026-10-30.json`
  一般與 RAG 數字相近）。Gemma 4 E2B 全 GPU、Whisper small（中英自動偵測、beam 1）、路由與
  檢索並行（檢索上限 0.7 s）、MuseTalk 待機喚醒與每輪啟動批次、Edge TTS；
  3 輪 96 句，0 失敗；交接 30／30 實際交接。
- 環境：RTX 4090、MuseTalk、單一舞台會話。測試題的 RAG 問題與現場知識庫（一份
  文件）不符，最終 96 輪中檢索 55 輪為空、10 輪逾時、1 輪命中。

### 對照規格目標（P50／P95，秒）

| 類別 | 規格目標 | 基準線（用戶端收到） | 最終（用戶端收到） | **最終感知首音** | 判定 |
| --- | --- | ---: | ---: | ---: | --- |
| 一般 | 第一階段 ≤ 1.2／≤ 2.5；第二階段 ≤ 1.0／≤ 1.5 | 4.09／4.43 | 2.09／2.47 | **1.99／2.37** | P95 達第一階段；P50 未達，第二階段未達 |
| RAG | 第一階段 ≤ 1.6／≤ 3.0 | 3.93／4.22 | 2.16／2.41 | **2.06／2.30** | P95 達標；P50 未達 |
| 交接 | 第一階段 ≤ 1.6／≤ 3.0 | 2.48／2.69 | 1.30／2.04 | **1.20／1.94** | 達第一階段；30 輪全數實際交接 |

其他起點（P50／P95，秒）：

| 類別 | 首音延遲：基準線 → 最終 | 伺服器接受 Prompt 起算：基準線 → 最終 |
| --- | --- | --- |
| 一般 | 3.37／3.74 → 1.40／1.75 | 2.92／3.19 → 1.32／1.69 |
| RAG | 3.22／3.52 → 1.43／1.64 | 2.74／3.06 → 1.37／1.58 |
| 交接 | 1.80／2.00 → 0.67／1.25 | 1.35／1.54 → 0.60／1.18 |

交接輪次聽到的第一段是交接說明；接手角色回覆的首音（伺服器接受交接問題起算）
P50／P95 1.96／2.30 → 1.09／1.71 s。

### 一般輪次的組成（P50，秒）

| 段 | 基準線 | 最終 | 主要改動 |
| --- | ---: | ---: | --- |
| VAD 拖尾（人聲低於 −40 dBFS 後仍判為語音） | 未量 | 0.08 | — |
| 靜音等待（實測時 `min_silence_ms: 300`，10 幀＝0.32 s） | 0.32 | 0.32 | 之後預設改為 192（6 幀＝0.19 s），待重量 |
| 上行（含伺服器 aiortc 抖動緩衝） | 未量 | 0.09 | — |
| 語音辨識 | 0.41 | 0.07 | beam 1、記憶體直傳、只在中英文間偵測 |
| 主回答前 | 1.29（路由 0.69＋檢索 0.50，串行） | 0.56（檢索等待） | 路由與檢索並行，主回答不等路由（[ADR 0022](adr/0022-run-routing-retrieval-and-answer-concurrently.md)）；路由 0.33 s 不在首音路徑上 |
| 首片段（主回答開始 → 第一個可播回覆片段） | 0.93 | 0.42 | Gemma 4 E2B（首 token 0.63 → 0.25 s）、首個片段例外、模型資訊查詢移出每輪路徑 |
| 片段到 WebRTC 送出 | 0.62 | 0.36 | 開口前待機靜音修剪、MuseTalk 待機喚醒與每輪啟動批次 |
| Edge TTS 開頭無聲段 | 未量 | 0.10 | — |
| **感知首音延遲** | 4.09（用戶端收到） | **2.00** | 各段 P50 不完全相加 |

### 剩餘瓶頸與下一步

第一階段一般輪次 P50（1.2 s）與第二階段都未達成。依大小排列：

| 段 | P50 | 下一步 | 狀態 |
| --- | ---: | --- | --- |
| 檢索等待 | 0.56 s | 已改用 llama.cpp CPU 提供 bge-m3（issue 15）：RAGFlow 檢索 P50 0.11／P95 0.15 s，上限 0.7 → 0.3 s；實際輪次待重量 | 已完成，待 `measure_first_audio.py` 重量 |
| 首片段 | 0.42 s | E2B 首 token 0.25 s；首句 15 字規則（只限簡答，看板口語不受限）遵循率低（7/29） | 已實作首個片段例外，停頓聽感待使用者確認 |
| 片段到送出 | 0.36 s | Edge TTS 首段 PCM 0.16 s＋MuseTalk 首批 0.19 s；換本機 TTS 後會變大（見下） | 每輪啟動批次的嘴型同步待使用者目視確認 |
| 靜音等待 | 0.32 s | 使用者決定改為約 0.2 s：預設 `min_silence_ms: 192`（6 幀＝0.19 s，省約 0.13 s）。句中停頓可能被當成說完，待現場試用；預判端點最多再省 0.16 s，需新 ADR | 預設已改，待實機重量（issue 16） |
| Edge 開頭無聲段 | 0.10 s | 前導上限 0.16 → 0.04 s，可能切掉輕聲字首；換 TTS 後重量 | 待使用者決定 |
| 上行 | 0.09 s | 舞台 loopback 的伺服器抖動緩衝 prefetch 4 → 1 約省 0.06 s，需 patch aiortc | 待使用者決定 |
| VAD 拖尾 | 0.08 s | 門檻 0.5 → 0.7 只省約 0.01 s，不建議 | 不調整 |

即使檢索降到約 0.1 s，一般輪次 P50 估計仍約 1.5 s；達到第二階段還需要上表其他
選項或預判端點。

**TTS 影響**：最終數字使用 Edge TTS（僅供開發）。BreezyVoice 已整合，但與
MuseTalk、E2B 共用 RTX 4090 時第一個片段（約 15 字）合成 P50／P95 2.48／2.94 s，
Fun-CosyVoice3（已移除）為 1.77／1.89 s，都遠高於規格的 0.4／0.7 s；現在改用
BreezyVoice，感知首音約增加 2.3 s。2026-10-30 使用者決定 TTS 只保留 BreezyVoice 與
Edge TTS（issue 18），其餘引擎已移除。試聽評分、方向決定與 8 小時穩定性測試待使用者
（issue 10）。顯存：E2B＋MuseTalk 共 18.0 GB，再載 BreezyVoice 峰值 23.9／24.5 GB。

**英文交接路由**：修正前的量測交接 30 輪只有 18 輪實際交接，失敗的全是英文句
（E2B 在長對話中漏填縣市、把臺南寫成「臺南」）。依規格加入天氣關鍵字初篩
（`src/profiles/weather_keywords.py`，issue 17）後，最終驗證 30／30。

### 9 月串流 soak（歷史）

`.scratch/reply-voice-streaming/real-soak-mouth-continuity-50-rerun.json`（50 回合，
Edge TTS＋MuseTalk，早於 VAD 靜音縮短、RAGFlow、角色路由與綠幕合成）的非延遲
gate 仍是最近一次 50 回合結果：A/V 偏差 P95 0.06 s（≤ 0.08）、插話停止 P95
0.000345 s（≤ 0.2）、恢復收音 P95 0.30 s（≤ 0.5）、最大媒體債務 0.24 s（≤ 2）、
stale output 0。回答收尾的 720×1280 嘴部 ROI settling 平均 1.596 ms、最大
3.966 ms。這些 gate 在現行組合下尚未以 50 回合重跑。

## 控制台語音驗證

即時演播控制台的「語音驗證」面板透過目前已連線的 `VoiceTurnSession` 執行
LLM → TTS → Avatar → WebRTC 完整播放，不是模擬器，也不繞過正式流程。正常對話
尚未完成時伺服器拒絕啟動測試；測試輪次建立後、排入 LLM 前即關閉收音 gate，
測試期間的麥克風 frame 不能建立或取代輪次。

- 每筆紀錄保存測試名稱、Prompt、實際播放回覆、UTC 起訖時間、LLM／TTS／ASR／
  數字人／角色／回覆模式快照（不含 API key）、各階段延遲與 Gate 判定。
- 以 schema version 1 原子寫入 `logs/voice-test-history.json`，保留最近 200 筆；
  可用 `NOVA_AVATAR_VOICE_TEST_HISTORY` 指定位置。重啟時未完成的紀錄標記為
  `interrupted`。一般對話不寫入此歷史，也不保存麥克風音訊。
- 單次判定使用首音 ≤ 2.5 s、A/V 偏差 ≤ 0.08 s、最大媒體債務 ≤ 2 s、stale
  output = 0，並要求輪次完整完成且有實際播放回覆。首音起點是伺服器接受 Prompt
  的時間，不含 VAD／ASR。插話停止與恢復收音對單次測試顯示「不適用」。
- 一鍵測試適合日常 smoke test、設定比較與回歸紀錄，不能取代 50 回合正式 soak。

量測語義：A/V 偏差只配對同一 `turn_id`、generation 與 `media_sequence` 的音訊與
影像，不以兩條軌道各自最近的 PTS 相減。`webrtc_video:late_video` 是有界視訊佇列
滿時淘汰最舊未播畫格以維持音訊主時鐘，顯示為「視訊背壓丟幀」，不計入
stale-output Gate；generation fence、取消或提交前檢查丟棄的媒體才算 stale output。

## 目前驗證狀態

- 離線專案檢查：passed。它驗證目前設定、品牌／授權必備檔案、核心 Python
  整合依賴與 MuseTalk commercial review profile，且不寫入音訊。
- 完整 Python suite：1305 passed、3 skipped、83 subtests passed（2026-10-30，工作樹；
  另 2 項需要不進版控的本機資產，在工作樹中固定失敗）。
- Web：210 tests passed；ESLint passed。
- Vite production build：passed。
- 嘴型連續、待機轉場、settling、字幕生命週期、看板提交、可編輯規則、RAGFlow
  檢索與背景合成均有專用回歸測試。

## 正式執行設定

以下為 `config/config.yaml` 的 checked-in 預設。本機 `config/runtime_overrides.yaml`
（不進版控）由控制台寫入並優先生效，確認實際執行狀態時需一併檢查。

- `reply_streaming.enabled: false`：v1 保留舊有與串流兩種回覆模式，串流由設定頁或 YAML 明確啟用。
- `reply_streaming.semantic_wait_seconds: 0.5`：弱語意邊界預設等待上限（原為 5 s），
  到期時若已有可獨立朗讀的子句即在該邊界釋放（由計時器觸發，不等下一個 token）；
  控制台可在 0.5–30 s 間調整。
- `reply_streaming.decoupled_audio_clock: false`：正式路徑維持單一 renderer-owned 音訊 producer。
- `vad.min_silence_ms: 192`：連續靜音約 0.2 s 視為使用者說完。等待以 Silero 32 ms 幀向上取整，
  192 正好 6 幀＝0.192 s；設 200 會進位成 7 幀＝0.224 s。
- `asr.type: whisper`、`model_size: small`：語音輪次一律只在中文與英文間自動偵測；
  `asr.language` 只影響 `/asr` 上傳辨識。FunASR 可選，但只辨識中文。
- `llm.provider: llamacpp`、`model: gemma-4-E2B_q4_0-it`：後端自行啟動 llama-server
  並附掛 mmproj 供附件看圖；Qwen3.5-9B 可選。`llamacpp_allow_partial_offload: false`
  時放不下全部層數即啟動失敗並說明。預設不需要 11434 的 Ollama。
- `tts.type: edgetts`：僅供開發（非公開端點、無正式商用授權、斷網即無法發聲），
  控制台標示 Development only；正式聲線待 TTS 評比決定。`tts` 只是第一次建立數位人
  設定檔時主數位人的初始聲音；之後預設聲音一律跟隨主數位人設定檔，
  `runtime_overrides.yaml` 不再保存 `tts`。
- 檢索上限 0.3 s（`RETRIEVAL_BUDGET_SECONDS`，issue 15 實測 P95 0.15 s 的兩倍）：逾時本輪不帶檢索並在控制台顯示。
- `model.musetalk.mouth_continuity: true`、`mouth_continuity_idle_alignment: true`、
  `settling_enabled: true`、`avatar_transition: true`；settling 預設 5 影格，限制在 4–6 影格。
- 音訊是媒體主時鐘；視訊不得讓音訊等待，也不得以 catch-up burst 追趕。

## 場域試營運基線

場域試營運的範圍、凍結組合與暫緩項目見 [`.scratch/field-pilot/spec.md`](../.scratch/field-pilot/spec.md)。

- 實際執行組合：Edge TTS（僅供開發）＋ MuseTalk ＋ faster-whisper small（中英自動偵測）＋
  llama.cpp（Gemma 4 E2B）＋ Silero VAD ＋ 串流回覆開啟；其他引擎不納入場域驗收。
  場域規格原本凍結 FunASR 與 Qwen3.5-9B，2026-10-30 依首音延遲改善的決定改為上述
  組合：FunASR 速度與 Whisper 同級但不辨識英文（Q24），E2B 經 30 題品質報告由使用者
  接受（Q26）。Edge TTS 仍須在上線前換成本機 TTS。
- Edge TTS 依賴雲端，端點曾於 2026-10-10 前後改變；握手被拒時自動換主機。上線前仍須實測出聲。
- Edge TTS 延遲主要來自通往新端點的連線偶發停頓（1–10 秒，獨立程序與純 TCP 同時觀測到）與 429 限流。
  已建立的連線送出請求後 0.1–0.3 秒即有音訊，且可連續合成、閒置 60 秒仍可用，因此 `tts.edge_connection_reuse`
  （預設開啟）預先備妥並重用 WebSocket，把建立連線移出首音路徑；429 以 0.2–0.4 秒隨機退避並多給一次嘗試；
  預取最多一段。同時開第二條連線的對沖經實測無效（停頓成批發生），未採用。
- 舞台 kiosk 模式（`scripts/start-kiosk.sh`）與訪客對話重置（預設 10 秒，控制台可設）已實作；
  真實語音鏈路尚未在場域主機上驗證。
- 暫緩：控制台認證、錄影路由、場域內容範圍、開機自啟與驗收標準。

## v1 執行邊界

- 正式串流 SLO 與首音延遲實測只涵蓋 Edge TTS＋MuseTalk、單一活躍會話；改用本機
  TTS 後需重量。
- 其他 TTS／Avatar adapter 可用，但不宣稱具有與主力組合相同的實機延遲基準。
- direct PCM／decoupled audio clock 是預設關閉的實驗路徑，不屬於 v1 正式保證。
- 綠幕合成依即時色差計算柔邊，尚未保存逐幀全身 alpha；切換數位人仍須斷開會話。
- RAGFlow 的每位數位人知識庫選擇是功能路由，不是存取控制。
- 後端收到 SIGTERM／SIGINT 時先關閉 WebRTC 連線、語音工作階段與 owned llama-server，
  15 秒內未完成即先停止 owned llama-server／CosyVoice 再強制結束；關閉期間再收到的訊號一律忽略。
  啟動腳本停止後端時最多等 20 秒才 SIGKILL。
- SIGKILL、斷電或核心崩潰無法觸發程序清理；外部管理的 llama-server 不由本程式終止。
- `config/config_commercial.yaml` 是商業審查的部署起點，不是對任何模型、聲音、
  權重、資料集或服務的商業授權保證。
