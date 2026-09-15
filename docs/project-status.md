# 目前專案基線

更新日期：2026-09-15

此文件記錄 Nova Avatar 目前已交付能力、可重現的驗證結果與執行邊界。
新的工作項目、舊實驗的清理與 release handoff 流程請依
[`current-project-workflow.md`](current-project-workflow.md)；可選引擎與商業審查
邊界請依 [`software-stack.md`](software-stack.md)。最新語音恢復與延遲驗證見
[`voice-conversation-latency-and-recovery-test-record.md`](voice-conversation-latency-and-recovery-test-record.md)。

## 已完成範圍

| 領域 | v1 已完成能力 |
| --- | --- |
| 對話與傳輸 | WebRTC 雙向音訊、Avatar 影像、事件通道、免按對話、按住說話、插話、斷線清理與伺服器擁有的單一有效輪次 |
| 語音輸入 | Silero 服務端端點偵測、faster-whisper／FunASR、繁體轉換、STT 預熱與執行期設定 |
| 回覆生成 | Ollama／llama.cpp、串流 token、交易式 history、柔性回覆長度、單一 LLM 可編輯回覆規則 |
| 看板回答 | SIMPLE／BOARD 協定、口語摘要與看板項目分流、顯示確認、已顯示項目上下文與輪次隔離 |
| 語音與字幕 | 多 TTS adapter、可靠語意切片、播放提交、字幕顯示窗口；字幕在播放結束或輪次提交後才淡出 |
| 數字人 | MuseTalk（Supported / Commercial）、Wav2Lip（Research / Non-commercial）、Ultralight、ER-NeRF、TalkingGaussian；MuseTalk 段落連續、待機對齊與 12 影格回答收尾 settling |
| 設定與生命週期 | LLM、Avatar、VAD、STT、TTS、Prompt、Rule、回覆模式與舞台設定；owned llama-server 正常關閉清理 |
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

## 目前驗證狀態

- 離線專案檢查：passed。它驗證目前設定、品牌／授權必備檔案、核心 Python
  整合依賴與 MuseTalk commercial review profile，且不寫入音訊。
- 本輪語音流程 focused Python tests：144 passed、12 subtests passed。
- Web：74 tests passed。
- Vite production build：passed。
- 使用 `uv sync --extra funasr --extra musetalk` 後，完整 Python suite 收集 411 項：
  408 passed、3 skipped。FunASR、MuseTalk 與控制台語音驗證的對應測試路徑均已驗證。
- 嘴型連續、待機對齊、settling、字幕生命週期、看板提交與可編輯規則均有專用回歸測試。
- 控制台「語音驗證」使用目前 WebRTC 會話執行真實播放；一般對話不寫入測試歷史，
  測試 Prompt、實際播放文字、環境與延遲紀錄保存在 `logs/voice-test-history.json`。

## 正式執行設定

- `reply_streaming.enabled: false`：v1 保留舊有與串流兩種回覆模式，串流由設定頁或 YAML 明確啟用。
- `reply_streaming.semantic_wait_seconds: 0.5`：弱語意邊界預設等待上限，控制台仍可調整。
- `reply_streaming.decoupled_audio_clock: false`：正式路徑維持單一 renderer-owned 音訊 producer。
- `model.musetalk.mouth_continuity: true`、`idle_alignment: true`、`settling_enabled: true`；
  checked-in default 的 `settling_frames: 5`，並以最小 4、最大 6 影格限制。
- 音訊是媒體主時鐘；視訊不得讓音訊等待，也不得以 catch-up burst 追趕。

## v1 執行邊界

- 正式串流 SLO 只涵蓋 Edge TTS＋MuseTalk、單一活躍會話。
- 其他 TTS／Avatar adapter 可用，但不宣稱具有與主力組合相同的實機延遲基準。
- direct PCM／decoupled audio clock 是預設關閉的實驗路徑，不屬於 v1 正式保證。
- SIGKILL、斷電或核心崩潰無法觸發程序清理；外部管理的 llama-server 不由本程式終止。
- `config/config_commercial.yaml` 是商業審查的部署起點，不是對任何模型、聲音、
  權重、資料集或服務的商業授權保證。
