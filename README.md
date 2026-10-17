# Nova Avatar

Nova Avatar 是即時對話數位人系統。瀏覽器透過 WebRTC 傳送麥克風音訊，後端依序
完成語音端點偵測、辨識、模型回答、語音合成與數位人渲染，再把影音和字幕送回
瀏覽器。控制台用來對話與調整設定，`/stage.html` 是獨立的數位人舞台。

> 本專案由 Kedreamix/Linly-Talker-Stream 衍生，現由 HongXian0903 獨立維護。
> 上游與第三方來源見 [NOTICE](NOTICE) 和
> [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 目前版本提供什麼

- 服務端 Silero VAD、啟用麥克風後的免按對話、按住說話與插話；語音、字幕和畫面以對話輪次
  隔離，取消或斷線後不再交付舊輪次內容。
- faster-whisper／FunASR 辨識、Ollama／llama.cpp 回答，以及 Edge TTS 等可選
  語音引擎。主要數位人引擎是 MuseTalk，其他引擎的支援與授權見下文。
- 可選的語意片段串流回覆：完整回答尚未產生時即可開始合成語音。預設仍使用
  一次交付完整回答的模式；Edge TTS＋MuseTalk 的串流組合已有實機驗證。
- 獨立控制台和舞台、字幕、看板回答、Prompt／回覆規則、模型與角色設定，
  以及控制台內的真實語音鏈路測試。
- 新增 RAGFlow 文件檢索：管理者在 RAGFlow 匯入文件；控制台為目前數位人
  選取知識庫、測試檢索並啟用。Nova 仍使用目前選定的 LLM 產生回答，
  RAGFlow 只提供本輪的參考片段。

架構與已驗證的執行邊界見 [目前專案基線](docs/project-status.md)、
[軟體組合](docs/software-stack.md) 和 [架構決策紀錄](docs/adr/)；
綠幕數位人與背景合成見 [ADR 0014](docs/adr/0014-compose-green-screen-avatars-on-server.md)。

## 安裝 Nova Avatar

以下以 Linux x86_64、NVIDIA GPU、MuseTalk 為例。先備妥：

| 項目 | 需求 |
| --- | --- |
| GPU | NVIDIA GPU、可用的 `nvidia-smi`；顯存需同時容納數位人與本機 LLM |
| Python | 安裝腳本以 uv 管理 Python 3.10.19，保留既有 `.venv` |
| 系統工具 | Git、FFmpeg、OpenSSL、Node.js 22+／npm、C++ 編譯工具 |
| CUDA | PyTorch 固定 cu124；首次編譯 mmcv 需 CUDA Toolkit 12.4／`nvcc` |
| LLM | 預設為 Ollama `qwen3.5:4b`，也可設定 llama.cpp 或其他服務 |

在專案根目錄依序執行：

```bash
git clone https://github.com/s0966066980/nova-avatar.git
cd nova-avatar
bash scripts/setup-env.sh musetalk
bash scripts/download_musetalk_weights.sh
bash scripts/create_ssl_certs.sh
```

安裝腳本會準備 Python、MuseTalk／OpenMMLab 與前端依賴；重跑保留既有
環境。權重下載沿用專案固定的套件，不會升級系統 pip 或強制切換鏡像。
SSL 腳本不再要求互動輸入，已有憑證時會保留；預設服務使用 HTTPS。

接著備妥角色素材：可在控制台匯入正面閉嘴影片，或執行：

```bash
uv run python src/avatars/musetalk/genavatar_musetalk.py \
  --avatar_id musetalk_avatar1 --file /path/to/silent_video.mp4
```

確認 Ollama 已啟動並有 `qwen3.5:4b`，或先將設定改成可用的模型服務。
角色、STT、TTS 與回覆模式可在控制台調整。系統套件、CUDA 編譯排錯、
權重檢查與依賴更新方式見 [完整安裝流程](docs/installation.md)。

### 啟用 TensorRT GPU 加速（選用）

完成上述 MuseTalk 安裝與權重下載後，在目標 GPU 上執行：

```bash
bash scripts/setup-tensorrt.sh
uv run python scripts/verify-musetalk-tensorrt.py
```

第一行安裝固定的 CUDA 12 TensorRT 10、建立完整 UNet／VAE FP16 引擎，
比較 batch 1、4、8 的速度與誤差，通過後才把引擎路徑寫入本機
`config/runtime_overrides.yaml`。第二行透過正式載入流程，以目前角色
latent 與 Whisper 特徵驗證合併推論及畫面誤差。之後正常啟動即可。

本機 RTX 4090 的 batch 8 角色模型合併推論實測為 **96.19 → 38.49 ms，
約 2.50 倍**，輸出 PSNR 57.72 dB；此數字只涵蓋 UNet＋完整 VAE＋
CPU 像素交付，不能視為整體對話或 WebRTC 加速倍率。

重驗已建好的引擎可使用 `bash scripts/setup-tensorrt.sh --verify-only`。
建置參數、量測結果與回復 PyTorch 的方法見
[TensorRT 安裝與驗證](docs/installation.md#tensorrt-安裝與驗證) 和
[x86 效能紀錄](docs/x86-performance.md)。

## 啟動與使用

在專案根目錄執行：

```bash
bash scripts/start-all.sh config/config.yaml
```

此命令啟動後端與 Web 控制台。執行過 `ragflow.sh prepare` 的主機會一併
啟動 RAGFlow；它尚未準備好時，啟動腳本會顯示提示並繼續啟動 Nova。
若 RAGFlow 已由其他命令啟動，`start-all.sh` 會沿用該實例。按
`Ctrl+C` 停止 Nova，以及這次由 `start-all.sh` 帶起的 RAGFlow 服務；
既有 RAGFlow 實例會保持執行。暫時不啟動檢索服務可執行
`NOVA_START_RAGFLOW=0 bash scripts/start-all.sh config/config.yaml`。

| 入口 | 預設位址 | 用途 |
| --- | --- | --- |
| Web 控制台 | `https://localhost:3000` | 對話、設定、語音驗證 |
| 數位人舞台 | `https://localhost:3000/stage.html` | 獨立演播畫面 |
| 後端健康檢查 | `https://localhost:8010/health` | 確認 Nova 後端就緒 |
| RAGFlow 管理頁 | `http://127.0.0.1:8088` | 建立知識庫、上傳與解析文件 |

上表依預設 YAML 的 `app.ssl: true` 顯示 HTTPS；若關閉 SSL，Nova
控制台和後端網址改用 HTTP。RAGFlow 管理頁只綁定主機 loopback，從另一
台電腦無法直接連線。後端日誌在 `logs/start-all-backend.log`。

啟動後，在控制台選擇數位人與模型，使用文字訊息或啟用麥克風開始對話。
需要文件檢索時，到「設定 → 數位人、AI 與知識設定」選定數位人，
在「RAG 知識文本」檢查連線、勾選知識庫，再選擇全部文件或指定文本。
按「測試目前草稿」確認文件片段，啟用檢索後「儲存並套用」。
RAGFlow 故障或逾時時，Nova 繼續一般回答並在控制台顯示狀態；
沒有命中時照常回答，不宣稱具有文件依據。檢索片段只是參考預覽，
不代表正式引文。檢索設定依數位人設定檔分開保存，初始為關閉。

### 角色設定與即時交接

「系統設定中心 → 數位人、AI 與知識設定」集中管理身分 Prompt、LLM、
回覆模式、看板規則、RAG 知識庫與指定文件，以及聲音和工具。
先從設定檔清單選擇要編輯的數位人；切換設定檔會保留各自未儲存的草稿，
共用人物素材的角色仍有各自的知識範圍。在「角色組合、交接與轉場」
選主數位人及專門數位人，設定交接規則、說明與各方向轉場。
首次啟動會將現有有效設定複製為主角色，不覆蓋之後的修改。
設定保存在 `config/avatar_profiles.yaml`；「僅儲存草稿」不改變目前對話，
「儲存並套用」會等待目前輪次結束，更新舞台與控制台。關閉交接時同樣
使用主數位人的完整設定檔。重啟時會載入已儲存設定；舊設定缺少的回覆模式、
語意等待上限與看板項目上限會從現有有效設定遷移一次。

首版即時組合使用兩位 MuseTalk 數位人，共用同一 LLM 服務與模型，以及同一
語音合成引擎；聲線可不同。主角色依交接規則判斷接手主題，播完交接說明後轉場，
專門角色回答原問題。舞台及控制台可返回主角色，WebRTC 連線與各角色記憶會保留。
舞台閒置重置會清除本訪客全部角色記憶並回到主角色。

去程、回程可各自選淡入淡出、左右滑動、縮放，或上傳 MP4／MOV／WebM
轉場影片（100 MiB、30 秒內）。影片會完整驗證，轉為靜音、25 fps；
共同輸出為 720×1280，保留原比例及共用背景。
舞台連線時由訪客發問；控制台需先選「切到控制台測試」才可輸入，測試期間舞台暫停收音。

天氣工具使用中央氣象署 CWA，授權碼只從服務端的 `NOVA_CWA_API_KEY`
（亦支援 `CWA_API_KEY`）或已排除 Git 的 `config/cwa.env` 載入。
可執行 `uv run python scripts/configure-cwa.py` 隱藏輸入既有授權碼。
角色設定可指定場域縣市與鄉鎮；留白且訪客未提供地點時會先詢問。
提供目前觀測與未來七天預報，降雨機率只使用來源提供的前三天資料；
可直接詢問「今天台北天氣如何？」等縣市範圍問題，不必指定鄉鎮即可交接。
有指定鄉鎮時查詢該鄉鎮預報；僅指定縣市時使用縣市預報，現在觀測則明示測站與觀測時間。
缺值、過舊或查詢失敗會明確說明，發布時間未知時不當成最新一報。

驗證已啟用的角色組合（使用合成測試語音，不保存原始音訊或對話）：

```bash
uv run python scripts/run_role_soak.py --turns 50 --output .scratch/live-avatar-switch/role-soak.json
```

此工具使用真實 WebRTC 收送音畫，量測舞台與控制台各自的交接；瀏覽器觀看端的
音畫順序與嘴型仍需另外驗收。

### 場域 kiosk 啟動

場域主機要讓訪客直接使用數位人舞台時，在後端與前端啟動後執行：

```bash
bash scripts/start-kiosk.sh
```

腳本以 Chrome／Chromium 全螢幕開啟 `/stage.html?kiosk=1`，並預先放行聲音播放與
麥克風，使用獨立的瀏覽器設定檔 `.local/kiosk-profile`。舞台看到 `kiosk=1` 會自動
連線，連線中斷時依 2、3、5、8、10 秒退避自動重連，訪客只看到「數字人暫時無法使用」
這類簡短提示。一般瀏覽器開啟 `/stage.html` 不受影響，仍是點一下進入。
可用 `NOVA_KIOSK_URL`、`NOVA_KIOSK_BROWSER`、`NOVA_KIOSK_PROFILE` 覆寫網址、瀏覽器與
設定檔位置。

如需分開啟動 Nova 前後端，可在不同終端執行
`bash scripts/start-backend.sh config/config.yaml` 和
`bash scripts/start-frontend.sh config/config.yaml`；RAGFlow 則以
`bash scripts/ragflow.sh up`／`down` 獨立管理。

## 安裝 RAGFlow 文件檢索（選用）

RAGFlow 使用獨立的 Docker Compose 專案、資料卷，以及主機上的 CPU
嵌入服務。需要 Docker、Compose 2.40 以上、使用者層級 systemd 和 Ollama。
部署腳本固定取得 RAGFlow `v0.27.2`，管理頁與 API 只開放在本機。
未完成此節時，Nova 的一般對話仍可使用。

首次部署：

```bash
bash scripts/ragflow.sh install-docker   # 已有 Docker/Compose 可略過
bash scripts/ragflow.sh prepare
bash scripts/ragflow.sh validate
bash scripts/ragflow.sh pull-model
bash scripts/ragflow.sh up
```

在部署主機開啟 `http://127.0.0.1:8088`，依序完成：

1. 建立管理帳號，並立即更改初始密碼。初始密碼在未納入版控的
   `.local/ragflow/upstream/docker/.env` 的 `ADMIN_DEFAULT_PASSWORD`。
2. 在模型供應者設定新增 Ollama 執行個體：服務位址
   `http://host.docker.internal:11435`，嵌入模型 `bge-m3`。
3. 建立知識庫，上傳文件並完成解析。文件上傳／解析只在 RAGFlow 介面管理。
4. 建立 API 金鑰：點右上角頭像 → 設定 → **API** 頁，建立並複製金鑰。
5. 把金鑰寫入本機後端環境檔，不要貼進控制台或瀏覽器：

```bash
cp config/ragflow.env.example config/ragflow.env
chmod 600 config/ragflow.env
```

在 `config/ragflow.env` 填入 `NOVA_RAGFLOW_API_KEY`；預設
`NOVA_RAGFLOW_URL=http://127.0.0.1:9380`。`start-all.sh` 與
`start-backend.sh` 只把這份檔案載入後端；前端程序會清掉這兩個變數。
`config/ragflow.env.example` 只可保留空白金鑰欄位，不得填入真實金鑰。

6. 重啟 Nova 後端。在「設定 → 數位人、AI 與知識設定」選定數位人，
   開啟「RAG 知識文本」確認顯示「RAGFlow 已連線」，選知識庫與文本範圍、
   測試目前草稿，再啟用檢索並儲存套用。文件上傳與解析仍由 RAGFlow 管理。

推送到 GitHub 前，確認金鑰與 RAGFlow 密碼仍只在本機。`.gitignore` 已忽略
`config/ragflow.env`、`config/ragflow_settings.yaml` 與 `.local/ragflow/`。
可提交的是空白範本 `config/ragflow.env.example`。推送前執行：

```bash
git status
git check-ignore -v config/ragflow.env .local/ragflow
git diff --cached
```

`config/ragflow.env` 必須顯示為 ignored；暫存區不得出現金鑰、管理密碼或
`.local/ragflow/`。金鑰也不得寫進 README、issue、PR 或截圖。若金鑰曾進入
版本庫，先在 RAGFlow 撤銷並重建，再從 Git 歷史移除。

建置步驟、行為、隔離、故障說明與驗證清單見
[RAGFlow 本機檢索整合](docs/ragflow.md)。

## 設定與檢查

`config/config.yaml` 設定服務埠、SSL、Avatar、VAD、STT、LLM、TTS、
字幕與回覆模式；控制台可調整常用選項。切換 Avatar、STT 或 TTS 引擎前，
先中斷目前 WebRTC 會話。RAGFlow 的非機密角色設定另存於
`config/ragflow_settings.yaml`；API 金鑰留在 `config/ragflow.env`。

開發與交付檢查：

```bash
uv sync --inexact --group dev --extra vad --extra musetalk
# 已啟用 TensorRT 時，同步依賴加上 --extra tensorrt。
uv run python scripts/check-integration.py
uv run pytest
cd web
npm test
npm run build
```

`check-integration.py` 預設執行離線檢查。已準備好設定檔指定的 LLM
與 Edge TTS 後，可執行 `uv run python scripts/check-integration.py --smoke`
檢查實際服務。真實 WebRTC 語音回合的驗證方式見
[目前專案基線](docs/project-status.md)。

x86 的影音排程、CPU 合成基準與可選完整模型 TensorRT 建置，見
[x86 即時效能優化](docs/x86-performance.md)。

## 授權與來源

Nova Avatar 自行撰寫的程式採 [Apache-2.0](LICENSE)。MuseTalk 程式採
MIT 授權；模型、權重與依賴另有條款。內含 Wav2Lip 整合僅供
**Research / Non-commercial** 使用，不得視為可商用。RAGFlow、BGE-M3、
語音、資料集與外部服務也須各自核對條款；根目錄授權不會擴及它們。
詳見 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)、
[NOTICE](NOTICE) 和 [軟體組合](docs/software-stack.md)。
