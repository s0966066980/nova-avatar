# v1 Base 狀態

更新日期：2026-09-11

目前工作樹定義為 Nova Avatar 第一版基線。此文件只記錄已交付能力、已通過驗證與執行邊界；後續需求重新立項時再建立新的規格與計畫。

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

## v1 自動驗證

- Python：355 tests，352 passed，3 skipped（依環境條件跳過）。
- Web：67 tests passed。
- Vite production build：passed。
- 嘴型連續、待機對齊、settling、字幕生命週期、看板提交與可編輯規則均有專用回歸測試。
- 測試稽核未發現可安全整檔移除的測試；現有測試各自覆蓋仍受支援的引擎、路由、協定或 UI 行為。

## 正式執行設定

- `reply_streaming.enabled: false`：v1 保留舊有與串流兩種回覆模式，串流由設定頁或 YAML 明確啟用。
- `reply_streaming.decoupled_audio_clock: false`：正式路徑維持單一 renderer-owned 音訊 producer。
- `model.musetalk.mouth_continuity: true`、`idle_alignment: true`、`settling_enabled: true`、`settling_frames: 12`。
- 音訊是媒體主時鐘；視訊不得讓音訊等待，也不得以 catch-up burst 追趕。

## v1 執行邊界

- 正式串流 SLO 只涵蓋 Edge TTS＋MuseTalk、單一活躍會話。
- 其他 TTS／Avatar adapter 可用，但不宣稱具有與主力組合相同的實機延遲基準。
- direct PCM／decoupled audio clock 是預設關閉的實驗路徑，不屬於 v1 正式保證。
- SIGKILL、斷電或核心崩潰無法觸發程序清理；外部管理的 llama-server 不由本程式終止。
