# 目前專案基線

更新日期：2026-09-25

此文件記錄 Nova Avatar 目前已交付能力、可重現的驗證結果與執行邊界。
新的工作項目、舊實驗的清理與 release handoff 流程請依
[`current-project-workflow.md`](current-project-workflow.md)；可選引擎與商業審查
邊界請依 [`software-stack.md`](software-stack.md)；設計決定見 [`adr/`](adr/)。

## 已完成範圍

| 領域 | v1 已完成能力 |
| --- | --- |
| 對話與傳輸 | WebRTC 雙向音訊、Avatar 影像、事件通道、免按對話、按住說話、插話、斷線清理與伺服器擁有的單一有效輪次 |
| 語音輸入 | Silero 服務端端點偵測（說完判定靜音 300 ms）、faster-whisper／FunASR、繁體轉換、STT 預熱、無效音訊品質閘門與執行期設定 |
| 回覆生成 | Ollama／llama.cpp、串流 token、交易式 history、柔性回覆長度、單一 LLM 可編輯回覆規則、控制台集中管理的助手身分與 Prompt |
| 知識庫檢索 | 可選的本機 RAGFlow 檢索：依數位人選擇知識庫、控制台測試檢索、GPU BGE-M3 嵌入；見 [`ragflow.md`](ragflow.md) |
| 看板回答 | SIMPLE／BOARD 協定、口語摘要與看板項目分流、顯示確認、已顯示項目上下文與輪次隔離 |
| 語音與字幕 | 多 TTS adapter、可靠語意切片、播放提交、字幕顯示窗口；字幕在播放結束或輪次提交後才淡出 |
| 數字人 | MuseTalk（Supported / Commercial）、Wav2Lip（Research / Non-commercial）、Ultralight、ER-NeRF、TalkingGaussian；MuseTalk 段落連續、待機相位匹配與 4–6 影格回答收尾 settling |
| 演播場景 | MuseTalk 綠幕數位人於後端色鍵合成至共用背景（圖片、GIF、循環影片），講話中可切換背景；角色與背景可封存／復原 |
| 設定與生命週期 | LLM、Avatar、VAD、STT、TTS、Prompt、Rule、回覆模式、知識庫與舞台設定；owned llama-server 正常關閉清理 |
| 控制台驗證 | 自訂 Prompt 的一鍵真實語音鏈路測試、逐階段延遲與既有 SLO Gate、環境快照、實際播放回覆及本機持久歷史 |
| 安全與隱私 | generation fence、取消後拒絕 stale output、有界媒體背壓；未啟動錄製時不持久保存原始麥克風音訊 |

## 正式實機基準

環境：NVIDIA RTX 4090、本機 llama.cpp、Edge TTS、MuseTalk、WebRTC、單一活躍會話。

正式報告：`.scratch/reply-voice-streaming/real-soak-mouth-continuity-50-rerun.json`

| 指標 | 結果 | Gate |
| --- | ---: | ---: |
| 回合數 | 50 | 至少 50 |
| 首音 P50 | 1.185525 s | ≤ 1.2 s |
| 首音 P95 | 1.691548 s | ≤ 2.5 s |
| A/V 偏差 P95 | 0.06 s | ≤ 0.08 s |
| 插話停止 P95 | 0.000345 s | ≤ 0.2 s |
| 恢復收音 P95 | 0.301517 s | ≤ 0.5 s |
| 最大媒體債務 | 0.24 s | ≤ 2 s |
| stale output | 0 | 必須為 0 |

回答收尾的 720×1280 嘴部 ROI settling 實測平均 1.596 ms、最大 3.966 ms，不加入 GPU 推理或音訊等待。

此基準早於 VAD 靜音縮短、RAGFlow 檢索與綠幕背景合成，之後沒有重跑。更新正式
基準時，需在相同 Edge TTS＋MuseTalk 單會話條件下重跑至少 50 回合並以上表所有
gate 判定；啟用 FunASR 時同時記錄每輪 `stage_seconds.asr`，啟用 RAG 或綠幕時
另外標明，不得與此基準混用。

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
- 完整 Python suite：441 passed、3 skipped、50 subtests passed（2026-09-25）。
- Web：84 tests passed。
- Vite production build：passed；僅保留既有大 chunk 警告。
- 嘴型連續、待機轉場、settling、字幕生命週期、看板提交、可編輯規則、RAGFlow
  檢索與背景合成均有專用回歸測試。

## 正式執行設定

以下為 `config/config.yaml` 的 checked-in 預設。本機 `config/runtime_overrides.yaml`
（不進版控）由控制台寫入並優先生效，確認實際執行狀態時需一併檢查。

- `reply_streaming.enabled: false`：v1 保留舊有與串流兩種回覆模式，串流由設定頁或 YAML 明確啟用。
- `reply_streaming.semantic_wait_seconds: 0.5`：弱語意邊界預設等待上限（原為 5 s），
  到期時若已有可獨立朗讀的子句即在該邊界釋放；控制台可在 0.5–30 s 間調整。
- `reply_streaming.decoupled_audio_clock: false`：正式路徑維持單一 renderer-owned 音訊 producer。
- `vad.min_silence_ms: 300`：連續靜音 300 ms 視為使用者說完。
- `model.musetalk.mouth_continuity: true`、`mouth_continuity_idle_alignment: true`、
  `settling_enabled: true`、`avatar_transition: true`；settling 預設 5 影格，限制在 4–6 影格。
- 音訊是媒體主時鐘；視訊不得讓音訊等待，也不得以 catch-up burst 追趕。

## v1 執行邊界

- 正式串流 SLO 只涵蓋 Edge TTS＋MuseTalk、單一活躍會話。
- 其他 TTS／Avatar adapter 可用，但不宣稱具有與主力組合相同的實機延遲基準。
- direct PCM／decoupled audio clock 是預設關閉的實驗路徑，不屬於 v1 正式保證。
- 綠幕合成依即時色差計算柔邊，尚未保存逐幀全身 alpha；切換數位人仍須斷開會話。
- RAGFlow 的每位數位人知識庫選擇是功能路由，不是存取控制。
- SIGKILL、斷電或核心崩潰無法觸發程序清理；外部管理的 llama-server 不由本程式終止。
- `config/config_commercial.yaml` 是商業審查的部署起點，不是對任何模型、聲音、
  權重、資料集或服務的商業授權保證。
