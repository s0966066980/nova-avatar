<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# Nova Avatar 使用的模型（Jetson AGX Orin 版）

本文只說明 `jetson-orin` 分支。它列出這個分支的**出廠預設設定**使用哪些模型、
本機還備有哪些可切換的模型，以及哪些元件只是選用或受授權限制。

> [!IMPORTANT]
> Nova Avatar 的根目錄 [Apache-2.0](../LICENSE) 不涵蓋任何模型、權重、資料集、
> 聲音、人物素材或外部服務。本文的「授權依據」欄只記錄這個 repo 內查得到的證據，
> 查不到的一律標示「未稽核」，**不代表可商用**。商業發行前請逐項審閱
> [商用交付合規檢查清單](commercial-release-checklist.md)、
> [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) 與
> [來源標註稽核](source-attribution-audit.md)。
>
> **內部 POC 試用 vs 對外商業銷售**：[`config/config_commercial.yaml`](../config/config_commercial.yaml)
> 鎖定 Orin Phase A 商用基線（`Gemma-4-E2B` + `mmproj`、`faster-whisper small`、**預錄呈現**，排除含營收上限之 `LFM2.5` 與未稽核之 `qwen3.5`）。對外商業銷售仍須先解除兩項 **Blocking**：(1) 替換 `Edge TTS`，(2) 重錄具完整肖像／聲音授權之自有預錄人物素材（不得沿用開發測試角色 `musetalk_1`）。

## 閱讀前先分清兩種設定

- **出廠預設設定**：隨專案發行的 `config/config_jetson*.yaml`，本文以它為準。
- **執行期覆蓋設定**：每個部署自己在控制台保存的 `config/runtime_overrides.yaml`，
  啟動時會蓋過出廠預設，未被 Git 追蹤。所以某台機器實際使用的模型可能與本文不同，
  請以該機器控制台顯示的設定為準。

模型檔案不加入 Git，全新 checkout 需依 [README](../README.md#安裝步驟) 自行準備。

## A. 出廠預設的模型鏈路

`bash scripts/start-jetson.sh` 使用 [config_jetson.yaml](../config/config_jetson.yaml)。

| 環節 | 模型／元件 | 預設值與位置 | 授權依據 |
| --- | --- | --- | --- |
| 語音端點偵測（VAD） | Silero VAD | `vad.type: silero`、`device: cuda`、靜音 300 ms 判定說完 | `silero-vad` 6.2.1 套件 PyPI classifier 標示 MIT；wheel 內附 `.jit`/`.onnx` 權重但未附獨立 LICENSE 檔，**權重未獨立稽核**（見 THIRD_PARTY_NOTICES） |
| 語音轉文字（STT） | faster-whisper `base` | `asr.model_size: base`、`device: cuda`、輸出繁體；首次執行自動下載 `base`，不隨 repo 附帶 | Whisper 為 MIT（Copyright 2022 OpenAI，見 THIRD_PARTY_NOTICES）；商用基線改採本機 `whisper-small` |
| 語言模型（LLM） | LFM2.5-2.6B Q4_K_M | `llama/LFM2.5-2.6B-Q4_K_M.gguf`，由本機 CUDA llama.cpp v0.5.0 啟動 | **LFM Open License v1.0（自訂授權）**，商業使用以年營收低於 1,000 萬美元為條件，見本機 `llama/metadata/lfm2.5-2.6b/LICENSE`；**Phase A 商用基線改採 Apache-2.0 之 `Gemma-4-E2B`** |
| 語音合成（TTS） | Edge TTS | `tts.type: edgetts`；需要網路，不在本機推論 | `edge-tts` 7.2.8 套件 classifier 標示 LGPLv3；線上服務與聲音條款未過商用審查，**僅限內部 POC 試用，對外商用 Blocking 必換** |
| 數位人嘴型 | MuseTalk v1.5 | `models/musetalk/musetalkV15/unet.pth`，開發測試角色 `musetalk_1` 位於 `data/avatars/` | 程式碼 MIT（Copyright 2024 Tencent Music Entertainment Group）；權重未稽核；`musetalk_1` 標記為 `user_upload` 且無肖像／聲音授權，**對外商用 Blocking 必換**，Phase A 改採預錄呈現 |
| 嘴型推論加速 | MuseTalk UNet FP16 TensorRT engine | `.local/jetson/musetalk-unet-fp16.engine`，在 Orin 上由目前 UNet 建置，不入 Git | 衍生自 MuseTalk UNet 權重，該權重條款未稽核 |
| 嘴型輕量解碼 | TAESD（`madebyollin/taesd`） | `.local/jetson/taesd/`，固定 revision `614f76814bbe30edbe2e627ace1c2234c81a2c0e` | MIT，Copyright (c) 2023 Ollin Boer Bohan（見 THIRD_PARTY_NOTICES） |

說明：

- MuseTalk 仍使用原本的 `models/sd-vae/` 編碼角色素材，並使用 `models/musetalk/` 下的
  Whisper 音訊特徵提取器、`dwpose`、`s3fd` 與 `models/face-parse-bisent/` 人臉解析權重。
  這些權重的授權同樣未在 THIRD_PARTY_NOTICES 逐項列載，列為未稽核。
- TAESD 是近似解碼，牙齒與唇部細節會略柔化。TensorRT engine 初始化或執行失敗時回退
  PyTorch UNet，輕量解碼失敗時回退原 VAE；回退保留功能，但可能無法維持即時速度。
- 出廠預設的 `reply_streaming.enabled` 為 `false`，也就是使用**舊有回覆模式**。
  控制台可改為**回覆語音串流**。

### 其他兩個啟動模式

| 啟動模式 | 設定檔 | 載入的模型 |
| --- | --- | --- |
| `--read-aloud` | `config_jetson_read_aloud.yaml` | MuseTalk（TensorRT UNet、TAESD）與 TTS；不載入 LLM、VAD、ASR |
| `--realtime` | `config_jetson_realtime.yaml` | 同上，用於單一會話的音畫同步與低延遲診斷 |

## B. 本機已備、可切換的模型

下表是這台開發機的 `models/` 與 `llama/` 目前備有的檔案，可在控制台設定面板切換，
或修改設定檔。其他部署不一定備有，需自行下載。

### 語音轉文字

| 模型 | 位置 | 說明 | 授權依據 |
| --- | --- | --- | --- |
| Whisper small | `models/whisper-small/` | 官方 `openai/whisper-small`，revision `973afd24965f72e36ca33b3055d56a652f456b4d`，已轉為 CTranslate2 格式 | 目錄內 `LICENSE` 為 MIT（Copyright 2022 OpenAI） |
| Whisper large-v3-turbo | `models/whisper-large-v3-turbo/` | 官方 `openai/whisper-large-v3-turbo` 轉換版 | 目錄內 `LICENSE` 為 MIT（Copyright 2022 OpenAI） |
| FunASR paraformer-zh | `models/funasr/paraformer-zh/` | 選用的中文辨識，保留作比較基準，不列為正式選型（見下節） | FunASR 套件 1.4.15 metadata 標示 MIT；**模型授權未稽核**，THIRD_PARTY_NOTICES 要求使用前確認確切版本與模型授權 |

選擇 `small` 或 `turbo` 時，程式優先使用上列本機目錄。

### 語言模型（llama.cpp，放在 `llama/`）

| 模型 | 檔案 | 授權依據 |
| --- | --- | --- |
| LFM2.5-2.6B Q4_K_M（出廠預設） | `LFM2.5-2.6B-Q4_K_M.gguf` | LFM Open License v1.0，條件同上 |
| LFM2.5-1.2B-Instruct Q4_K_M | `LFM2.5-1.2B-Instruct-Q4_K_M.gguf` | LFM Open License v1.0，條件同上 |
| Gemma-4-E2B QAT q4_0（含視覺 mmproj） | `gemma-4-E2B_q4_0-it.gguf`、`gemma-4-E2B-it-mmproj.gguf` | 官方模型卡標示 Apache-2.0，固定 revision `675cff42a74c774d6cb76f76d8eacb49b48c9b93`（見 THIRD_PARTY_NOTICES） |
| Granite-4.2-3B Q4_K_M | `granite-4.2-3b-Q4_K_M.gguf` | 固定 revision README 標示 Apache-2.0，上游快照沒有獨立 LICENSE 檔，見 `llama/metadata/granite4.2-3b/` |
| Ministral-3-3B-Instruct-2512 Q4_K_M | `Ministral-3-3B-Instruct-2512-Q4_K_M.gguf` | 固定 revision README 標示 Apache-2.0，上游快照沒有獨立 LICENSE 檔，見 `llama/metadata/ministral3-3b/` |
| Qwen3.5-4B／2B UD-Q4_K_XL | `Qwen3.5-4B-UD-Q4_K_XL.gguf`、`Qwen3.5-2B-UD-Q4_K_XL.gguf` | **來源與授權未稽核**：沒有來源或授權紀錄 |

另有 `models/llm/Qwen3.5-4B-Q4_K_M.gguf`，同樣未稽核。`scripts/build-jetson-llama.sh --download-model`
會以固定 revision 下載 Qwen 模型並驗證 SHA-256，驗證檔案完整性不等於稽核授權。

Gemma-4-E2B 與其 mmproj 也用於**對話附件**的圖片與 PDF 頁面分析，見
[對話附件](conversation-attachments.md)。Ollama 也可作為相容的本機 LLM 服務。

### 選用的知識庫檢索與外部資料服務

| 元件 | 說明 | 授權依據 |
| --- | --- | --- |
| RAGFlow v0.27.2 | 獨立部署的檢索服務，只提供檢索片段，回答仍由 Nova 的 LLM 產生 | 程式碼 Apache-2.0；映像與相依服務（Elasticsearch、MySQL、MinIO-compatible、Valkey、Microsoft ODBC EULA）各有授權 |
| BGE-M3 | 由獨立的 Ollama v0.35.1 GPU 程序提供嵌入（預設停用） | **權重與訓練資料未在本 repo 獨立稽核（列為未稽核）**；模型卡見 <https://huggingface.co/BAAI/bge-m3>，商業交付知識庫前須另行覆核 |
| CWA OpenData（`src/weather/`） | 連線交通部中央氣象署開放資料 API（`https://opendata.cwa.gov.tw/`）提供台灣天氣查詢 | **非軟體權重，屬外部政府開放資料 API**：須依 OGDL v1.0 與平台規範標示「交通部中央氣象署」出處，並由商業營運主體申請自有正式 API Key（不可沿用開發測試 Key）；停用時設 `weather.enabled: false` |

詳見 [RAGFlow 本機檢索整合](ragflow.md) 與 [ARM64 建置報告](reports/ragflow-arm64.md)。

## C. 選用或受限的元件

這些元件的程式碼在 repo 內，但**本分支沒有驗證它們的 ARM64 相依套件**，
不列為 Jetson 支援項目。

| 元件 | 狀態 | 授權說明 |
| --- | --- | --- |
| Wav2Lip（Research / Non-commercial） | 僅供研究與個人非商業用途 | **不得視為具商業許可**。其整合與上游權重不得放進商業發行，見 [Wav2Lip 限制聲明](../third_party/licenses/Wav2Lip-NON-COMMERCIAL-NOTICE.txt) |
| ER-NeRF、TalkingGaussian、UltraLight | 選用 | 須逐一審閱來源、子模組、資料集與模型；部分 TalkingGaussian 子模組帶有非商業研究條款 |
| GPT-SoVITS、CosyVoice、Fun-CosyVoice、Fish TTS、XTTS、IndexTTS2 | 選用的替代 TTS | 須逐一審閱程式碼、模型、聲音與 checkpoint 條款 |

## Whisper small 與 turbo 的比較

出廠預設使用 faster-whisper `base`。為了支援中英文舞台語系，另外比較過官方
OpenAI Whisper small 與 turbo：

- 兩者都能在本機 CUDA 執行，權重授權為 MIT，且都直接由官方權重轉換。
- 以八題合成語音比較，small 暖測中位數 0.575 秒、程序 RSS 1.591 GiB；
  turbo 為 1.327 秒、2.984 GiB。比較當時為兼顧延遲與資源而採用 small，turbo 保留可選。
- 中英混說仍有誤辨。這次不是真人口音或噪音環境的驗收。

上述結論只涵蓋這兩個 Whisper 權重，不涵蓋其他模型、聲音或線上服務，也不構成商業授權保證。

FunASR 只保留作比較基準：正式採用的語音模型需要「可本機部署、權重授權允許商用，
且主要開發機構與基礎權重非中國大陸」，並明列資料與教師來源的已知與未知。

## 更換模型時怎麼驗收

更換模型屬於**模型替換驗收**：以現用模型為基準，先確認候選的來源與授權，再優先維持
回答品質、回應速度、播放連續性及資源表現。只確認模型載得動不算通過。建議流程：

1. 先執行真實推論，不要只用 `torch.cuda.is_available()` 判斷：
   `uv run python scripts/check-cuda.py --models`。
2. LLM 更換後，用問候、隱含多步驟、差異比較、指定三項看板與純口述五種問題驗證，
   見 [對話模型、角色與回覆規則](llm-reply-rules.md)。
3. 在控制台以「語音驗證」跑真實語音鏈路。
4. 在本文補上新模型的來源與授權依據；查不到就寫「未稽核」。
