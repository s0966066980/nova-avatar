# Nova Avatar (Jetson Orin 版本)

Nova Avatar 是即時對話數位人系統。瀏覽器透過 WebRTC 傳送麥克風音訊，後端依序
完成語音端點偵測、辨識、模型回答、語音合成與數位人渲染，再把影音和字幕送回
瀏覽器。控制台用來對話與調整設定，`/stage.html` 是獨立的數位人演播舞台。

> 本專案由 Kedreamix/Linly-Talker-Stream 衍生，現由 HongXian0903 獨立維護。
> 上游與第三方來源見 [NOTICE](NOTICE) 和
> [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

此 `jetson-orin` 分支專為 **NVIDIA Jetson AGX Orin**（ARM64、JetPack 7／L4T R39.2.1、CUDA 13.2、cuDNN 9、Python 3.11）進行深度移植與加速優化。包含完整的邊緣端推論加速、TensorRT UNet、TAESD 輕量嘴型解碼、ARM64 原生編譯 CTranslate2、CUDA llama.cpp 以及原生 ARM64 RAGFlow 知識庫整合。

---

## Jetson 版本核心架構與加速特色

1. **全鏈路即時串流（WebRTC）**：
   - 瀏覽器與後端透過 WebRTC 雙向通訊，音訊以伺服器端 Silero VAD（CUDA 加速，說完靜音判定 300ms）進行端點偵測。
   - 免按對話、按住說話與插話機制完整支援；取消或重連時透過輪次隔離（Generation Fence）丟棄過期媒體，不產生殘留雜音。
   - 瀏覽器接收端設定 160ms 音訊抖動緩衝目標（Jitter Buffer Target），吸收邊緣端模型並行推論時的微小抖動。

2. **MuseTalk 數位人推論加速**：
   - **TensorRT UNet FP16 Engine**：在 Orin 上將 MuseTalk UNet 建置為 TensorRT 引擎（`.local/jetson/musetalk-unet-fp16.engine`），大幅降低 GPU 推論耗時。
   - **TAESD 輕量嘴型解碼**：以本機 `madebyollin/taesd`（`.local/jetson/taesd/`）替換傳統繁重的 VAE 解碼，達成直式 720p（720×1280、25fps、batch 8）的即時生成需求。
   - **平滑轉場與收尾穩定**：具備嘴型連續控制（Mouth Continuity）、待機相位對齊（Idle Alignment）與 4–6 影格收尾 Settling，避免閉嘴閃跳。
   - 若 TensorRT 引擎或 TAESD 載入失敗，具備自動回退至原 PyTorch UNet／VAE 的保護機制。

3. **語音輸入（STT／ASR）在 CUDA 執行**：
   - PyPI ARM64 的 CTranslate2 官方 wheel 預設不具備 CUDA 後端。本專案以主機 CUDA 13.2 與 cuDNN 針對 Orin SM 8.7 原生編譯 CTranslate2 wheel 與函式庫，使 **faster-whisper** 與 **FunASR** 均完整運行於 CUDA。

4. **語言模型（LLM）本機 CUDA 推論**：
   - 內建針對 Orin SM 8.7 編譯之 CUDA **llama.cpp**，以 `torch.cuda.mem_get_info()` 支援 Orin 共享顯存配置。
   - 預設使用 `llama/LFM2.5-2.6B-Q4_K_M.gguf`，具備 64-token 有限思考、GBNF 格式約束與看板／口語分離；亦支援 `llama/Qwen3.5-4B-UD-Q4_K_XL.gguf`、`Qwen3.5-2B-UD-Q4_K_XL.gguf` 或本機 Ollama 服務。

5. **綠幕背景合成（Server-Side Chroma Key）**：
   - 支援將 MuseTalk 綠幕數位人於伺服器端色鍵去背並合成至共用背景（圖片、GIF 或循環影片），背景邊界自動適配，講話中可動態切換背景。

6. **原生 ARM64 RAGFlow 知識庫檢索**：
   - 提供專屬 ARM64 Docker Compose 整合（RAGFlow v0.27.2），BGE-M3 嵌入模型由獨立的 GPU 程序加速，提供毫秒級的本機向量檢索。

7. **CPU 執行緒隔離防爭用**：
   - Orin CPU 由系統、WebRTC 媒體排程、解碼與推論共享。啟動腳本限制底層 BLAS/OpenCV 線程為 1（`OMP_NUM_THREADS=1`），杜絕 CPU 爭用導致的音訊撕裂與卡頓。

---

## 系統需求

- **硬體**：NVIDIA Jetson AGX Orin 64GB / 32GB（或相容之 Orin 模組）。
- **作業系統**：Ubuntu 24.04 LTS（aarch64）、JetPack 7 / L4T R39.2.1。
- **CUDA 環境**：CUDA Toolkit 13.2（安裝於 `/usr/local/cuda`）、cuDNN 9。
- **Python**：Python 3.11（搭配 [uv](https://docs.astral.sh/uv/) 套件管理工具）。
- **前端工具**：Node.js 22 與 npm。
- **系統相依套件**：
  ```bash
  sudo apt-get update
  sudo apt-get install -y ffmpeg ninja-build cmake build-essential libopenblas-dev pkg-config lsof
  ```

---

## 安裝步驟

取得專案原始碼（切換至 `jetson-orin` 分支）：

```bash
git clone --branch jetson-orin https://github.com/s0966066980/nova-avatar.git
cd nova-avatar
```

### 1. 執行 Jetson 環境建置

執行專屬 Jetson 環境安裝指令碼：

```bash
bash scripts/setup-jetson.sh
```

> **說明**：亦可執行 `bash scripts/setup-env.sh musetalk`，腳本偵測到 aarch64 Tegra 平台後會自動轉交 `setup-jetson.sh`。該腳本會執行：
> 1. 編譯 ARM64 CUDA 13.2 原生 CTranslate2 函式庫與 wheel（存放於 `.local/jetson/`）。
> 2. 建立 Python 3.11 虛擬環境並安裝相容之 PyTorch 2.11 cu130 ARM64 wheels。
> 3. 自動修復 cuSPARSELt 0.8.0 wheel 的 manylinux metadata tag。
> 4. 同步專案相依套件（`uv sync --extra vad --extra musetalk --extra funasr`）。
> 5. 建置 Vue 3 前端控制台（`npm ci && npm run build`）。
> 6. 執行 `scripts/check-cuda.py` 自檢矩陣運算與 CUDA 可用性。

### 2. 編譯本機 llama.cpp

```bash
bash scripts/build-jetson-llama.sh
```

此腳本會以 `GGML_CUDA=ON` 與 Orin SM 87 架構編譯 llama.cpp v0.5.0，並產出可執行檔至 `.local/jetson/llama.cpp/`。若需要自動下載推薦模型，可加上 `--download-model`。

### 3. 下載模型權重與準備 Engine

1. **MuseTalk 基礎權重**：
   ```bash
   bash scripts/download_musetalk_weights.sh
   ```
   檢查 `models/musetalk/`、`models/sd-vae/` 與人臉解析權重是否齊全。

2. **TAESD 輕量嘴型解碼器**：
   下載 `madebyollin/taesd` 至 `.local/jetson/taesd`：
   ```bash
   uvx --from huggingface_hub hf download madebyollin/taesd \
     config.json diffusion_pytorch_model.safetensors README.md \
     --revision 614f76814bbe30edbe2e627ace1c2234c81a2c0e \
     --local-dir .local/jetson/taesd
   ```

3. **TensorRT UNet Engine**：
   確認 `.local/jetson/musetalk-unet-fp16.engine` 存在（若換機或更新 MuseTalk 權重，需透過 `.scratch/realtime-avatar/export_unet.py` 重新匯出與建置）。

4. **LLM GGUF 模型**：
   將 GGUF 模型放置於專案根目錄的 `llama/` 目錄中。例如：
   - `llama/LFM2.5-2.6B-Q4_K_M.gguf`（`config_jetson.yaml` 預設模型）
   - `llama/Qwen3.5-4B-UD-Q4_K_XL.gguf`

5. **數位人形象素材**：
   預設角色素材放置於 `data/avatars/musetalk_1/`。

### 4. 產生本機 SSL 憑證

瀏覽器 WebRTC 麥克風權限需要 HTTPS 安全連線：

```bash
bash scripts/create_ssl_certs.sh
```

將於 `ssl_certs/` 產生本機憑證檔（`localhost.crt` 與 `localhost.key`）。

---

## 啟動與使用

### 啟動模式選擇

專案提供專屬 Jetson 啟動腳本，支援多種情境：

#### 1. Jetson 一般對話模式（推薦）

```bash
bash scripts/start-jetson.sh
```

- 使用 `config/config_jetson.yaml`。
- 初始 MuseTalk 設定使用 TensorRT UNet 與 TAESD；後續沿用控制台保存的呈現方式與畫質。
- Silero VAD（CUDA）、faster-whisper（CUDA）與 llama.cpp（CUDA）全鏈路啟動。
- Edge TTS 合成語音。若已部署 RAGFlow 則會自動帶起檢索服務。
- 保留控制台在 `config/runtime_overrides.yaml` 保存的使用者設定。

#### 2. 固定朗讀加速模式（--read-aloud）

```bash
bash scripts/start-jetson.sh --read-aloud
```

- 使用 `config/config_jetson_read_aloud.yaml`。
- 專用於固定文字的流暢度與口型驗證，**不載入 LLM、VAD 與 ASR**，忽略暫存覆蓋設定，節省資源。

#### 3. 即時診斷模式（--realtime）

```bash
bash scripts/start-jetson.sh --realtime
```

- 使用 `config/config_jetson_realtime.yaml` 進行音畫同步與低延遲診斷。

### 服務入口網址

服務啟動後，可在本機瀏覽器開啟（從區域網路其他裝置連線時，請將 `localhost` 替換為 Jetson 的區網 IP）：

| 入口 | 預設位址 | 用途說明 |
| --- | --- | --- |
| **Web 控制台** | `https://localhost:3000` | 數位人對話互動、各項參數微調、語音鏈路測試 |
| **數位人獨立舞台** | `https://localhost:3000/stage.html` | 乾淨演播視窗，支援綠幕與背景即時合成 |
| **後端健康檢查** | `https://localhost:8010/health` | 檢視後端服務與模型是否就緒（HTTP 200 / `ready: true`） |
| **RAGFlow 管理介面** | `http://127.0.0.1:8088` | 文件上傳、解析與知識庫管理（僅本機 loopback） |

後端執行日誌位於 `logs/start-all-backend.log`。按 `Ctrl+C` 可安全退出所有相關程序。

---

## 原生 ARM64 RAGFlow 知識庫檢索（選用）

Nova Avatar 支援透過 RAGFlow 檢索本機知識庫，為數位人提供參考資料（由 Nova 既有 LLM 總結回答，RAGFlow 僅提供檢索片段）。

在 Jetson ARM64 上，使用專屬原生建置流程：

```bash
# 1. 建置原生 ARM64 映像（固定使用 v0.27.2 commit a024bea0）
bash scripts/ragflow.sh build

# 2. 啟動 RAGFlow 容器與主機 GPU 嵌入程序（BGE-M3）
bash scripts/ragflow.sh up

# 3. 下載嵌入模型並預熱
bash scripts/ragflow.sh pull-model

# 4. 自動連線與建立 API 金鑰
bash scripts/ragflow.sh connect

# 5. 檢視服務狀態
bash scripts/ragflow.sh status
```

連線設定與金鑰會自動寫入 `config/ragflow.env`（檔案權限 `0600`，由 `.gitignore` 忽略，嚴禁提交進 Git）。

在控制台「設定 → 知識庫檢索」確認顯示「RAGFlow 已連線」，勾選知識庫並執行「測試檢索」後即可啟用。詳細建置與驗證說明見 [RAGFlow 本機檢索整合](docs/ragflow.md) 與 [ARM64 建置報告](docs/reports/ragflow-arm64.md)。

---

## 驗證與品質測試

在提交與發布前，請依序執行以下各項測試：

```bash
# 1. 深度 CUDA 算子與實際模型推論檢查（含 MuseTalk、faster-whisper、FunASR、Silero）
uv run python scripts/check-cuda.py --models

# 2. 品牌、授權與專案整合契約稽核
uv run python scripts/check-integration.py

# 3. Python 測試套件
uv run pytest

# 4. 前端測試與生產環境建置
cd web
npm test
npm run build
cd ..
```

---

## 相關技術文件

- [NVIDIA AGX Orin 建置與 CUDA 驗證細節](docs/jetson-orin.md)
- [數字人即時生成與 TensorRT UNet 診斷](docs/realtime-avatar.md)
- [固定文字朗讀與音畫同步優化](docs/fixed-read-aloud.md)
- [LFM 模型相容性與 720p／1080p 實測分析](docs/lfm-resolution.md)
- [RAGFlow 本機檢索整合指南](docs/ragflow.md)
- [預錄數位人、五秒說話素材與場景錄影](docs/prerecorded-avatars.md)
- [專案軟體組合與邊界](docs/software-stack.md)
- [架構決策紀錄（ADR）目錄](docs/adr/)

---

## 授權與來源標註

- **Nova Avatar** 獨立撰寫之程式碼採 [Apache-2.0](LICENSE) 授權。
- **MuseTalk** 程式碼採 MIT 授權（版權所有 Tencent Music Entertainment Group）；其模型權重及相依套件另受其個別條款約束。
- 專案內整合之 **Wav2Lip** 僅供 **Research / Non-commercial**（學術／個人非商業用途），不得視為具商業許可。
- RAGFlow、BGE-M3、外部語音合成與各語言模型權重均具獨立授權，專案根目錄授權不擴及其權重與外部服務。
- 詳情請參閱 [NOTICE](NOTICE)、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 與 [來源標註稽核](docs/source-attribution-audit.md)。
