<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# Nova Avatar 軟體組合

更新日期：2026-11-28

Nova Avatar 是即時對話的數位人應用：瀏覽器麥克風音訊經 WebRTC 送到伺服器端的回合編排，
依序經過 VAD、STT、LLM、TTS、數位人渲染，再由 WebRTC 播放。某個元件可以被選用，不代表它的程式碼、
模型、聲音、服務或權重屬於根目錄 Apache-2.0 的授權範圍。

## Nova Avatar 核心

| 範圍 | 目前實作 |
| --- | --- |
| 傳輸與 API | `aiohttp`、`aiortc`、`av`、WebRTC 媒體與事件通道 |
| 對話控制 | 伺服器持有的目前回合、插話、世代隔離、播放提交 |
| 語音邊界 | 伺服器端 Silero VAD |
| 網頁控制台 | Vue 3、Vite、Bootstrap、瀏覽器媒體 API |
| 設定 | YAML 設定檔加上持久化的執行期設定 |

## 可選引擎

| 層 | 引擎 | 專案狀態 | 散布邊界 |
| --- | --- | --- | --- |
| STT | faster-whisper | 支援，也是唯一的 STT 引擎，預設 `small`；語音回合只在中文與英文之間自動偵測，beam 1，音訊只在記憶體 | 需審查所選的 Whisper 模型檔。 |
| LLM | llama.cpp | 支援，預設 Gemma 4 E2B（`gemma-4-E2B_q4_0-it`，附件看圖需搭配其 mmproj），所有層放在 GPU；Qwen3.5-9B 為選用 | Gemma 4 為 Apache-2.0（見 [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)）；其他模型需自行審查。 |
| LLM | Ollama | 選用，本機相容 OpenAI 的端點；預設不需要 | 需審查所選模型與端點的條款。 |
| TTS | Edge TTS | **Development only** | 仍是開發用的預設值。屬非公開的 Microsoft 端點，沒有正式商用授權，且需要網際網路。不得用於商業部署。 |
| TTS | BreezyVoice（聯發科技研究院）搭配 g2pW | 選用，本機台灣華語；在自有的 CosyVoice 行程內整段合成（CosyVoice v1 上游程式碼取自 `~/CosyVoice`，Apache-2.0）。在與 MuseTalk、LLM 共用的 RTX 4090 上，第一個片段約 2.5 秒（P50），所以尚未成為預設 | 程式碼與權重為 Apache-2.0（版本固定在 `services/tts/scripts/breezyvoice_weights.py`）；參考聲音需另行取得同意。見 [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)。 |
| TTS | Matcha-TTS voice models（`matcha` 引擎，sherpa-onnx，CPU 執行） | 選用；預設仍是 Edge TTS。`models/tts/<id>/` 下的聲線模型以同一個聲音說 zh-TW 與 en-US；聲線模型只能手動複製，不會下載（[voice-models.md](../guides/voice-models.md)）。`zh-tw-hsiaochen-edge` 於 2026-11-23 在 4 個 CPU 執行緒、未載入 MuseTalk 的條件下實測：暖機後首音 P50 0.050 秒、P95 0.067 秒；中文 CER 13.2%、英文 WER 5.6% | sherpa-onnx 為 Apache-2.0。沒有任何聲線模型可商用：`zh-tw-hsiaochen-edge` 是 **Development only**（以 Edge 輸出蒸餾，MSA §14(s)(iv)）；基底模型與由它微調的聲線模型是 **Research / Non-commercial**（訓練資料沒有文件）。見 [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)。 |
| 數位人 | MuseTalk | 支援，審查設定檔建議的路徑 | 程式碼為 MIT；模型與依賴套件各有獨立條款。 |
| 場景 | 伺服器端綠幕合成（`avatar/nova_render/scene/`） | 支援 MuseTalk 綠幕數位人 | 背景圖、影片、GIF 與來源素材需另外審查權利。 |
| 檢索 | RAGFlow `v0.27.2`，搭配專用 Ollama 行程提供的 BGE-M3 | 選用，預設停用 | 獨立的 Docker Compose 專案；需審查 RAGFlow、BGE-M3 與文件權利。見 [ragflow.md](../guides/ragflow.md)。 |

Qwen3-TTS 已於 2026-10-30 評估後移除（聲音複製會產生失控音訊），既不支援也不隨附。

ER-NeRF、TalkingGaussian、UltraLight 數位人引擎與 LFM 2.5 模型路徑已於 2026-11-24 移除，
它們不在目前版本的範圍內。Wav2Lip（Research / Non-commercial）在同一天依維護者要求移除；
仍含有它的舊版本保有該限制。

Fun-ASR-Nano-2512 STT 引擎（`funasr`）已於 2026-11-26 移除：它沒有被使用，維護者也不再需要。
已儲存的 `asr.type: funasr` 會改以 faster-whisper `small` 載入，舊的 `asr.output_script` 欄位會被忽略。

此組合的首音延遲實測（Edge TTS，2026-10-30）：一般語音回合 P50 2.00 秒、P95 2.22 秒，
從說話結束算到送出第一個可聽到的 WebRTC 回覆影格。定義、各階段拆解與剩餘瓶頸見
[project-status.md](project-status.md)。

## 外部執行環境需求

- Python 3.10–3.11 與 `uv`（後端依賴）。
- Node.js 與 npm（Vue 控制台）。
- FFmpeg（媒體處理）。
- 瀏覽器，以及瀏覽器媒體權限所需的安全來源（HTTPS 憑證）。
- NVIDIA 驅動程式與 CUDA 相容的執行環境，視所選數位人或機器學習引擎而定；各引擎的 CUDA 需求不同。
- 預設 LLM 需要 llama.cpp（含 CUDA 的 `llama-server`）；後端會自行啟動它，模型無法完整放進 GPU 時會失敗並說明原因。
  只有選用 Ollama 端點時才需要 Ollama。
- 只有啟用選用的 RAGFlow 檢索時才需要 Docker 與 Compose。

## 商業審查設定檔

[`config/config_commercial.yaml`](../../config/config_commercial.yaml) 是完整、可直接選用的設定，
組合為 MuseTalk、faster-whisper、Silero、本機相容 OpenAI 的 LLM 端點與 Edge TTS。
Edge TTS 只供開發，商業部署前必須替換。啟動方式：

```bash
bash scripts/start-all.sh config/config_commercial.yaml
```

控制台仍會顯示一般的執行期選項。商業散布前，部署者必須逐一確認所選的模型、聲音、服務、權重、
資料集與選用引擎。見 [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) 與
[來源歸屬稽核](source-attribution-audit.md)。
