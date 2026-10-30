<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->

# Linux x86_64 安裝流程

## 系統與 Python 環境

建議使用 Linux x86_64、NVIDIA GPU 與可用的 NVIDIA driver。先確認
`nvidia-smi` 能列出 GPU。需安裝 Git、FFmpeg、OpenSSL、Node.js 22+
及 npm；MuseTalk 的 OpenMMLab 擴充另需 C++ 編譯器、CUDA Toolkit 12.4
與 `nvcc`。PyTorch 固定為 2.5.0／CUDA 12.4，不要另外升級 Torch。

Ubuntu 的基礎套件可使用：

```bash
sudo apt-get update
sudo apt-get install git ffmpeg openssl build-essential python3-dev
```

Node.js 22+、NVIDIA driver 與 CUDA Toolkit 需另依主機環境安裝。
`nvidia-smi` 顯示的是 driver 支援的 CUDA 上限，不能代替 `nvcc --version`。

```bash
git clone https://github.com/s0966066980/nova-avatar.git
cd nova-avatar
bash scripts/setup-env.sh musetalk
```

腳本以 uv 安裝 Python 3.10.19、建立或沿用 `.venv`，同步 MuseTalk／VAD
依賴，再準備 OpenMMLab 與前端。無須 `source .venv/bin/activate`；以下
Python 指令皆用專案根目錄的 `uv run`。

如果找不到 CUDA Toolkit，可先設定既有安裝路徑：

```bash
export CUDA_HOME=/usr/local/cuda-12.4
export PATH="$CUDA_HOME/bin:$PATH"
nvcc --version
bash scripts/setup-env.sh musetalk
```

也支援專案內的 `.cuda-toolkit/`。Torch 2.5／cu124 的 mmcv 可能從原始碼
編譯，需預留時間與 RAM；失敗時先確認 CUDA、編譯器與 Torch 版本，
不要用升級全部依賴處理。只做純觀看／既有角色推論與新角色製作的依賴
需求不同；完整安裝腳本同時準備兩者。

## 權重、角色與 HTTPS

```bash
bash scripts/download_musetalk_weights.sh
bash scripts/download_musetalk_weights.sh --check
bash scripts/create_ssl_certs.sh
```

權重腳本使用目前環境的 `huggingface-hub` Python API，可重跑；預設從
官方 Hugging Face 下載，只有自行設定 `HF_ENDPOINT` 才使用鏡像。每個
來源固定在 `scripts/musetalk_weights.py` 記錄的 commit，每個檔案都以
SHA-256 驗證，不符即失敗（鏡像也無法替換權重）。`--check` 不下載，
同樣以 SHA-256 檢查 UNet、完整 SD VAE、Whisper、DWPose 與臉部分割
必要檔案。權重與來源影片的授權需另行核對，見
[第三方聲明](../THIRD_PARTY_NOTICES.md)。

準備正面閉嘴影片，在控制台匯入角色，或使用命令列：

```bash
uv run python src/avatars/musetalk/genavatar_musetalk.py \
  --avatar_id musetalk_avatar1 --file /path/to/silent_video.mp4
```

生成的 `data/avatars/<avatar_id>/` 包含幀、臉框、遮罩與 latent 快取。
在控制台選取該角色；素材不齊時服務仍可啟動，但尚不能建立該角色的
影音會話。TensorRT 引擎與角色快取是不同產物；更換同一模型下的角色
通常可共用引擎。

SSL 腳本保留既有完整憑證。偵測到 mkcert 時優先以本機 CA 簽發涵蓋
`localhost`、主機名稱與區網 IP 的憑證，管理者裝置匯入一次
`rootCA.pem` 即可信任（步驟見 README「管理者裝置信任本機 CA」）；
否則產生自簽憑證，瀏覽器首次使用需手動信任。預設 HTTPS 入口為後端的 `https://localhost:8010`。正式前端建置本身
不需要 SSL 私鑰；實際 HTTPS 開發服務與後端才需要。

## TensorRT 安裝與驗證

先完成 MuseTalk 環境與權重。此流程固定 `tensorrt-cu12==10.16.1.11`
及 `onnx==1.17.0`，沿用現有 Torch／cu124，不安裝 CUDA 13 變體。
安裝使用專案虛擬環境，無須系統 TensorRT／root 權限。
[NVIDIA Python 安裝文件](https://docs.nvidia.com/deeplearning/tensorrt/10.x.x/installing-tensorrt/install-pip.html)
說明 CUDA 12 套件選擇與 Builder 驗證；driver 需求見
[對應先決條件](https://docs.nvidia.com/deeplearning/tensorrt/10.x.x/installing-tensorrt/prerequisites.html)。

```bash
bash scripts/setup-tensorrt.sh
uv run python scripts/verify-musetalk-tensorrt.py
```

安裝器依序執行以下工作：

1. 用 `uv sync --inexact --extra vad --extra musetalk --extra tensorrt`
   安裝固定依賴，保留手動編譯的 mmcv 與已安裝的辨識引擎。
2. 檢查 CUDA、TensorRT import 與 Builder。
3. 匯出目前 UNet／完整 VAE，建立 batch 1–8 的動態 FP16 引擎。
4. 每個 batch 1、4、8 暖機五次，交替量測 PyTorch／TensorRT 各二十次。
   UNet 相對 L2 誤差須 ≤2%，VAE 樣本 PSNR 須 ≥35 dB；回退即失敗。
5. 只有目前設定 batch 已量得加速，且引擎 SHA-256 與驗證結果相符時，
   才更新本機 `config/runtime_overrides.yaml`。保留其他私有設定，原檔
   備份在引擎目錄，備份與覆蓋檔權限皆為 600。

第二個驗證指令經正式 `prepare_avatar_model` 載入兩個引擎，用目前角色
的 latent 和實際 Whisper 特徵比較 UNet＋VAE＋CPU 像素交付的合併時間，
並檢查畫面 PSNR ≥35 dB、無執行回退。音訊輸入為固定合成測試訊號，
不需要麥克風、外部 TTS 或 LLM。輸出的圖片只用於離線檢查。

產物皆在未納入 Git 的 `.local/tensorrt/musetalk/`：

| 產物 | 用途 |
| --- | --- |
| `unet-fp16.engine`、`vae-fp16.engine` | 正式推論引擎 |
| `comparison.json` | 各元件數值誤差、速度與環境版本 |
| `avatar-verification.json` | 正式載入與角色合併推論驗證 |
| `avatar-batch*-comparison.png` | 左 PyTorch、右 TensorRT 的角色臉部對照 |
| `*.onnx` | 建置中介模型，可在引擎完成後移除 |

重驗不重建：

```bash
bash scripts/setup-tensorrt.sh --verify-only
uv run python scripts/verify-musetalk-tensorrt.py
```

預設最大 batch 為 8；若部署設定 `model.batch_size` 更大，需用
`bash scripts/setup-tensorrt.sh --batch-size 16` 等指令重建。其他選項見
`uv run python scripts/build-musetalk-tensorrt.py --help`。

正常使用既有 `start-all.sh`／`start-backend.sh` 啟動，重啟後即套用路徑。
模型載入的 `Using optional TensorRT` 只表示引擎載入成功；仍應跑上述
驗證確認執行時沒有 `using original` 回退警告。TensorRT 只加速指定
MuseTalk 模型階段，不會直接加速 STT、LLM、TTS、編碼或網路。
實測紀錄及其範圍見 [x86 效能紀錄](x86-performance.md)。

GPU、模型權重或 TensorRT 版本變更後必須重建；不要搬用 Orin 引擎。
目前保留原 PyTorch 模型供回退，所以顯存會增加，應與本機 LLM 共跑
確認容量。引擎與數值檢查不能取代實際角色動態和 A/V 播放驗收。

要回復 PyTorch，在 `config/runtime_overrides.yaml` 將以下兩項設為空字串，
並重啟後端；控制台儲存其他設定會保留這些部署欄位：

```yaml
model:
  musetalk:
    unet_engine_path: ""
    vae_engine_path: ""
```

## 啟動、更新與交付檢查

確認設定中的 llama.cpp（或另選的 Ollama）服務與模型可用，再執行：

```bash
bash scripts/start-all.sh config/config.yaml
```

腳本先建置 `web/dist`，再由後端同源提供：控制台
`https://localhost:8010`，舞台 `https://localhost:8010/stage.html`（僅限本機），
健康檢查 `https://localhost:8010/health`。本機設定覆蓋主 YAML；變更設定前留意
`config/runtime_overrides.yaml` 的有效值。

### 停用預設 Ollama（11434）

預設設定選 `llamacpp` 端點，後端啟動時自行拉起 llama-server（`127.0.0.1:8080`），
不需要系統的 Ollama 服務（`ollama.service`，`127.0.0.1:11434`）。`ollama` 仍是
`llm.endpoints` 裡的可選端點；明確選用它的設定（控制台、數位人設定檔或舊的
`runtime_overrides.yaml`）照舊連 11434。

1. 先確認沒有設定在用 Ollama：`config/runtime_overrides.yaml` 的 `llm.endpoint`
   ／`base_url` 與 `config/avatar_profiles.yaml` 每個角色的 `llm.endpoint` 都不是
   `ollama`／`11434`（或在控制台「AI 模型」逐一檢查）。
2. 停用並關閉服務（在終端自行輸入 `sudo` 密碼）：

   ```bash
   sudo systemctl disable --now ollama
   ```

   要恢復：`sudo systemctl enable --now ollama`。

RAGFlow 的嵌入服務（`nova-ragflow-llamacpp-embedding.service`，Docker 橋接位址的
`11437`）是只用 CPU 的 llama.cpp，讀取 `models/ragflow/bge-m3-f16.gguf`，不依賴
11434，也不占顯存（見 [RAGFlow](ragflow.md)）。不要移除 Ollama 程式或模型目錄：
llama-server 可能從 `/usr/local/lib/ollama/cuda_v12` 載入 CUDA 函式庫，還原用的
舊 GPU 嵌入服務（`nova-ragflow-embedding.service`，`11435`）也沿用同一個執行檔與
`/usr/share/ollama/.ollama/models`。以下 RAGFlow 指令會連 11434，執行前先
`sudo systemctl start ollama`，完成後再 `sudo systemctl stop ollama`：
`ragflow.sh pull-model`（只在 `models/ragflow/bge-m3-f16.gguf` 尚不存在時，下載並
核對 BGE-M3）、`connect-chat`、`unify-models`、`sync-models`（三者只處理 RAGFlow
的聊天模型）；已啟用共用模式（`.local/ragflow/shared-ollama` 存在）時不要停用。

顯存：11434 沒有載入模型時幾乎不占 GPU，停用它主要是避免有人選到 Ollama 端點時
再載入一份模型。2026-10-30 以前 `nvidia-smi` 中約 1.6 GB 的 `ollama` 是 11435 的
BGE-M3 嵌入；改用 llama.cpp CPU 嵌入後已釋出。

更新已啟用 TensorRT 的環境：

```bash
uv sync --inexact --group dev --extra vad --extra musetalk --extra tensorrt
uv run python scripts/check-integration.py
uv run pytest
cd web
npm ci
npm test
npm run build
```

選用 FunASR 時加上 `--extra funasr`；未使用 TensorRT 時略過其 extra。
`uv sync` 預設會移除未選依賴，OpenMMLab 等手動安裝套件應使用
`--inexact` 保留；一般 `uv run` 預設保留額外套件。不要對此環境執行
`uv run --exact`。RAGFlow 為獨立選用部署，見 [RAGFlow 安裝](ragflow.md)。
