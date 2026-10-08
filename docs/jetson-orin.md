<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# NVIDIA AGX Orin 建置與 CUDA 驗證

Jetson 程式碼獨立維護於 `jetson-orin` 分支。取得此版本：

```bash
git clone --branch jetson-orin https://github.com/s0966066980/nova-avatar.git
cd nova-avatar
```

後續 Jetson 提交留在此分支，推送到自己的 Nova Avatar 倉庫；`main`
保留原有版本。此分支提供建置程式與設定，模型權重、TensorRT engine、
Docker 映像、資料庫、憑證及本機偏好需在目標主機另行準備。

這份流程適用於本機的 AGX Orin 64GB、Ubuntu 24.04 ARM64、Jetson Linux
R39.2.1、CUDA Toolkit 13.2 和 cuDNN 9。它不是 JetPack 6 的安裝流程；不要
在舊版 JetPack 上直接套用這組 CUDA 13 套件。

## 移植時修正的問題

- 從 x86 複製的 `.venv` 指向 x86 Python，`.cuda-toolkit/bin/nvcc` 也是
  x86 執行檔；原有 `web/node_modules` 含有 x86 原生套件。已保留備份並
  重建 ARM64 環境。
- x86 環境保留 PyTorch 2.5／cu124；ARM64 改用官方 cu130 的 PyTorch
  2.11.0、torchvision 0.26.0、torchaudio 2.11.0，以及 Python 3.11。
  CUDA 13.2 驅動可執行這組 CUDA 13.0 runtime；CUDA 擴充套件使用主機的
  13.2 Toolkit 編譯。
- PyPI CTranslate2 4.8.2 的 ARM64 wheel 沒有 CUDA backend。依照
  [上游編譯流程](https://opennmt.net/CTranslate2/installation.html)，以
  CUDA 13.2、cuDNN 和 Orin 的 SM 8.7 編譯原生函式庫與 Python wheel。
  `pyproject.toml` 固定使用此本地 wheel，避免 `uv run` 或 `uv sync`
  把它換回 CPU 版本。
- ARM64 推論省略 TensorFlow、TensorBoard 和 openmim；MuseTalk 的 UNet、
  VAE、Whisper 特徵提取仍用 CUDA。此路徑沿用已存在的 bundled SFD 裁切
  fallback，不編譯 mmcv／mmpose；既有角色快取不需要重新產生。
- Orin 的 `nvidia-smi` 無法回報可用顯存。llama.cpp 的 GPU 層數規劃改以
  `torch.cuda.mem_get_info()` 作為 fallback，並支援 CUDA 13 函式庫與
  user-local 執行檔 symlink。
- NVIDIA cuSPARSELt 0.8.0 的 ARM64 wheel 內含錯誤的 `manylinux2014_sbsa`
  metadata tag，會讓 uv 每次執行都重裝。setup 在確認函式庫是 ARM64 ELF
  後修正 tag 與 RECORD；保留函式庫和授權檔。
- 綠幕合成的像素搜尋改用 OpenCV，距離與遮罩計算只處理可見人物範圍。
  裁切保留背景邊界，和原實作的像素結果一致。

## 建置

先準備 NVIDIA 系統套件、`uv`、Node.js 22／npm，以及建置工具。這次
建置的 uv 與 Node 放在 `~/.local/bin`；Node 本體在專案的
`.local/toolchains/`。新主機可先依官方流程安裝這兩個工具，再執行：

```bash
export PATH="$HOME/.local/bin:$PATH"
sudo apt-get update
sudo apt-get install -y ffmpeg ninja-build cmake build-essential libopenblas-dev pkg-config lsof
bash scripts/setup-env.sh musetalk
bash scripts/build-jetson-llama.sh
```

`setup-env.sh` 在 Jetson 自動轉交 `setup-jetson.sh`，先建置本地
CTranslate2，再同步核心、VAD、MuseTalk 和 FunASR，最後建置前端。
舊 Python 環境會移到 `.venv-x86-backup-*`；前端使用 `npm ci` 重建。
CUDA Toolkit 使用 `/usr/local/cuda`，不使用移植過來的 `.cuda-toolkit`。

llama.cpp 固定為 v0.5.0，以 `GGML_CUDA=ON`、SM 87 編譯；可用
`NOVA_BUILD_JOBS=4` 減少編譯並行數。llama.cpp 模型統一放在專案的
`llama/` 目錄，目前使用 `llama/Qwen3.5-4B-UD-Q4_K_XL.gguf`。
已有此模型時不需下載；若需要下載，可加上 `--download-model`，
腳本固定下載 revision 並驗證 SHA-256。
MuseTalk、FunASR 與角色權重沿用 `models/`、`data/avatars/` 的既有檔案。
全新 checkout 仍需按 README 下載 MuseTalk 權重並準備角色素材。

本地 CTranslate2 wheel 位於 `.local/jetson/wheels/`，依賴的原生函式庫位於
`.local/jetson/ctranslate2/lib/`；兩者都需要保留。專案搬移到新位置時，
重新執行 setup 以更新原生函式庫路徑。之後同步依賴使用：

```bash
uv sync --extra vad --extra musetalk --extra funasr
```

## 啟動

```bash
bash scripts/start-jetson.sh
```

腳本先執行真實 CUDA 矩陣運算、FP16 卷積與 CTranslate2 能力檢查；CUDA
不可用時停止啟動。通過後使用 `config/config_jetson.yaml` 啟動前後端。
角色為 `musetalk_1`，語音辨識與 Silero VAD 設定 `device: cuda`，LLM
使用本機 CUDA llama.cpp。Edge TTS 使用外部服務；影音解碼、WebRTC 傳輸與
部分音訊前處理依然使用 CPU。

控制台：`https://localhost:3000`；舞台：
`https://localhost:3000/stage.html`；後端：`https://localhost:8010/health`。
其他電腦連線時，把 localhost 換成 Orin 的區網 IP。

控制台的 `config/runtime_overrides.yaml` 會覆蓋啟動設定。這次移植已把
ASR／VAD 裝置與 LLM 設定調整為 Orin 環境；之前的設定備份在
`.local/jetson/runtime_overrides-before-migration.yaml`。若另有本機模型，
可在設定面板改選；不要還原不存在的 x86 llama-server 或模型路徑。

若控制台顯示「這一輪回覆處理失敗」，可檢查
`logs/start-all-backend.log` 是否出現 `找不到 GGUF 模型`。本機模型預設會
從專案的 `llama/` 搜尋，因此使用一般啟動指令、且設定仍帶有舊的
`llamacpp_dir` 時，也能找到移植後的模型。明確指定的模型目錄仍優先；
Jetson 的 `.local/jetson/llama.cpp/build/bin/llama-server` 也可在沒有
PATH launcher 時直接被偵測。更新程式後需重新啟動後端才會生效。

RAGFlow 使用原生 ARM64 v0.27.2 映像，一般 Jetson 模式會自動帶起已準備的部署。
重建可執行 `bash scripts/ragflow.sh build`；部署與連線步驟見
[RAGFlow 本機檢索整合](ragflow.md)。`NOVA_START_RAGFLOW=0` 可略過，
`--read-aloud` 與 `--realtime` 朗讀模式仍略過。
Wav2Lip、ER-NeRF、TalkingGaussian 等其他 Avatar 尚未驗證 ARM64 相依套件。

## 驗證

```bash
uv run python scripts/check-cuda.py --models --output logs/jetson-cuda-verification.json
uv run python scripts/check-integration.py
uv run pytest
cd web
npm test
npm run build
```

`--models` 會載入真實 MuseTalk 權重，檢查模型參數與 buffer 位於 CUDA，
執行 UNet／VAE 暖機及 Whisper 音訊特徵提取，並執行 faster-whisper、
FunASR 與 Silero 推論。faster-whisper 首次執行會下載 base 模型；
沒有使用者錄音。驗證報告保存在 `logs/jetson-cuda-verification.json`。

此 cu130 PyTorch wheel 會顯示 Orin 8.7 的架構警告。這次已實際通過 CUDA
矩陣運算、FP16 卷積與上述四種模型推論；不要只用
`torch.cuda.is_available()` 判斷模型可用性。新增不同模型或 CUDA 算子時，
也需執行實際推論確認其支援。

套件與模型仍各自適用其授權；MuseTalk 的 MIT notice、Tencent Music
Entertainment Group attribution 和 Wav2Lip **Research / Non-commercial**
限制保留。來源與限制見 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。

## 本機驗證結果（2026-09-30）

| 項目 | 結果 | 紀錄 |
| --- | --- | --- |
| 真實 CUDA 模型推論 | MuseTalk、faster-whisper、FunASR、Silero 通過 | `logs/jetson-cuda-verification.json` |
| 品牌、授權與整合稽核 | 通過 | `logs/jetson-integration.log` |
| Python 全套測試 | 444 通過、4 跳過 | `logs/jetson-pytest.log` |
| 前端測試／production build | 84 通過／成功 | `logs/jetson-web-tests.log`、`logs/jetson-web-build.log` |
| LLM 與 Edge TTS smoke | 通過；LLM 首 token 0.88 秒 | `logs/jetson-smoke.log` |
| 真實 WebRTC 語音回合 | 兩輪完成，無過期事件交付 | `logs/jetson-voice-soak.json` |
| Orin GPU 活動 | 推論期間 GR3D 約 99% | `logs/jetson-gpu-activity.log` |

控制台回傳 HTTP 200，後端 `/health` 回報 `ready=true`、
`model_ready=true`。語音回合測得首音分別為 6.85 秒與 4.48 秒；此短測試
未達原有 2.5 秒首音目標，也未完成 50 輪、插話與重連的完整 soak gate。
報告的 `slo_pass=false` 因此保留原值。功能與 CUDA 路徑已驗證，Orin
即時延遲仍需另行調校，不能沿用 RTX 4090 的效能結論。

## Jetson 分支提交前驗證（2026-10-08）

- 品牌、授權與整合稽核通過。
- Python：533 通過、4 跳過、1 失敗。失敗項目仍為
  `test_chroma_composite_fits_the_render_frame_budget_on_a_portrait_avatar`；
  1080×1920 背景合成中位數 35.3ms，超過原有 30ms 門檻，未放寬門檻。
- 前端：93 項測試通過，production build 成功。
- 原生 ARM64 RAGFlow v0.27.2 的建置、健康檢查、中文文字檢索與
  掃描 PDF OCR 驗證見 [ARM64 建置報告](reports/ragflow-arm64.md)。

此提交保存目前可運行的 Jetson 版本；高解析度背景合成仍有上述效能限制。
