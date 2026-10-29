# Nova Avatar

Nova Avatar 是即時對話數位人系統。瀏覽器透過 WebRTC 傳送麥克風音訊，後端依序
完成語音端點偵測、辨識、模型回答、語音合成與數位人渲染，再把影音和字幕送回
瀏覽器。管理者在**控制台**對話與調整設定；訪客使用場域主機上的**數位人舞台**
（`/stage.html`）。

> 本專案由 Kedreamix/Linly-Talker-Stream 衍生，現由 HongXian0903 獨立維護。
> 上游與第三方來源見 [NOTICE](NOTICE) 和
> [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 目前版本提供什麼

- **對話鏈路**：服務端 Silero VAD、免按對話、按住說話與插話；faster-whisper small
  辨識（預設，中英文自動偵測），FunASR 可選（僅中文）；llama.cpp 回答（預設
  Gemma 4 E2B，Qwen3.5-9B 可選），也可接 Ollama 或其他 OpenAI 相容服務；語音預設
  Edge TTS（**僅供開發**），本機台灣華語 BreezyVoice 等為可選引擎。主要數位人引擎是
  MuseTalk，其他引擎的支援與授權見文末。
- **首音延遲**：角色路由、知識庫檢索與主回答同時開始。2026-10-30 以真實 WebRTC
  量測（Edge TTS），一般輪次從人聲結束到送出第一個可聽回覆音訊 P50 1.99 s、
  P95 2.37 s，P95 達第一階段目標、P50 尚未達到；起訖定義、各段組成與下一步見
  [目前專案基線](docs/project-status.md#首音延遲實測2026-10-30)。
- **輪次隔離與串流**：語音、字幕和畫面依對話輪次隔離，取消或斷線後不再交付
  舊內容。可選語意片段串流回覆，完整回答產生前即開始合成；預設仍一次交付完整
  回答，Edge TTS＋MuseTalk 串流組合已實機驗證。
- **控制台與舞台**：兩端各自對話；字幕、看板回答、Prompt／回覆規則、模型與
  角色設定，以及控制台內的真實語音鏈路測試。
- **角色組合與交接**：主數位人與專門數位人（例如天氣助手）依規則交接、轉場與
  返回，各自保有記憶。
- **對話記憶、雙語與附件**：按角色檢視記憶與 Context、中英文舞台與聲音、
  PDF／圖片問答。
- **RAGFlow 文件檢索（選用）**：為各數位人選取知識庫；回答仍由目前的 LLM 產生，
  RAGFlow 只提供本輪參考片段。
- **存取控制**：控制台需管理者登入；舞台只在場域主機本機開啟；LLM 端點、
  參考音訊與模型只能從伺服器管理的清單選擇。

架構與已驗證的執行邊界見 [目前專案基線](docs/project-status.md)、
[軟體組合](docs/software-stack.md) 和 [架構決策紀錄](docs/adr/)；信任邊界見
[ADR 0021](docs/adr/0021-stage-local-console-login.md)，綠幕數位人與背景合成見
[ADR 0014](docs/adr/0014-compose-green-screen-avatars-on-server.md)。

## 安裝

以下以 Linux x86_64、NVIDIA GPU、MuseTalk 為例。先備妥：

| 項目 | 需求 |
| --- | --- |
| GPU | NVIDIA GPU、可用的 `nvidia-smi`；顯存需同時容納數位人與本機 LLM |
| Python | 安裝腳本以 uv 管理 Python 3.10.19，保留既有 `.venv` |
| 系統工具 | Git、FFmpeg、OpenSSL、Node.js 22+／npm、C++ 編譯工具 |
| CUDA | PyTorch 固定 cu124；首次編譯 mmcv 需 CUDA Toolkit 12.4／`nvcc` |
| LLM | 預設 llama.cpp（後端自行啟動 llama-server，Gemma 4 E2B 全部層數放進 GPU，放不下即啟動失敗並說明）；Ollama 為可選端點，可加其他服務 |

在專案根目錄依序執行：

```bash
git clone https://github.com/s0966066980/nova-avatar.git
cd nova-avatar
bash scripts/setup-env.sh musetalk
bash scripts/download_musetalk_weights.sh
bash scripts/create_ssl_certs.sh
```

- 安裝腳本準備 Python、MuseTalk／OpenMMLab 與前端依賴；重跑會保留既有環境。
- uv、MuseTalk 權重、RAGFlow 映像與 BGE-M3 均固定版本並驗證 checksum／digest，
  不符即中止。Python 依賴以版控中的 `uv.lock` 鎖定。
- 控制台的 Bootstrap 與圖示由 npm 套件打包，場域斷網時仍可顯示。
- SSL 腳本不需互動輸入，已有憑證時會保留；預設服務使用 HTTPS。

系統套件、CUDA 編譯排錯、權重檢查與依賴更新見
[完整安裝流程](docs/installation.md)。

### 讓管理者裝置信任本機 CA（只需一次）

主機已安裝 [mkcert](https://github.com/FiloSottile/mkcert) 時，SSL 腳本會以它
建立本機 CA 簽發的憑證，涵蓋 `localhost`、主機名稱與區網 IP。其他名稱可加在
指令後，例如 `bash scripts/create_ssl_certs.sh nova.lan`。

1. 在主機執行 `mkcert -install`，讓本機舞台瀏覽器信任此 CA。
2. 把 `$(mkcert -CAROOT)/rootCA.pem` 複製到每台管理者裝置，匯入系統或瀏覽器的
   「受信任的根憑證」。之後重新簽發憑證不必再匯入。
3. `rootCA-key.pem` 只留在主機上，不要複製。

未安裝 mkcert（或設定 `NOVA_SSL_SELF_SIGNED=1`）時改產生自簽憑證，瀏覽器首次
連線需手動接受警告。

### 準備數位人素材

可在控制台匯入正面閉嘴影片，或執行：

```bash
uv run python src/avatars/musetalk/genavatar_musetalk.py \
  --avatar_id musetalk_avatar1 --file /path/to/silent_video.mp4
```

覆寫既有數位人時，舊素材會先移入回收桶；使用中或被設定檔引用的數位人不能覆寫。

### 啟用 TensorRT GPU 加速（選用）

完成 MuseTalk 安裝與權重下載後，在目標 GPU 上執行：

```bash
bash scripts/setup-tensorrt.sh
uv run python scripts/verify-musetalk-tensorrt.py
```

第一行安裝固定的 CUDA 12 TensorRT 10、建立 UNet／VAE FP16 引擎，比較 batch 1、
4、8 的速度與誤差，通過後才把引擎路徑寫入 `config/runtime_overrides.yaml`。
第二行以目前角色 latent 與 Whisper 特徵驗證合併推論及畫面誤差。

本機 RTX 4090 的 batch 8 合併推論實測為 **96.19 → 38.49 ms，約 2.50 倍**，
輸出 PSNR 57.72 dB；此數字只涵蓋 UNet＋完整 VAE＋CPU 像素交付，不代表整體
對話或 WebRTC 加速倍率。重驗引擎可用 `bash scripts/setup-tensorrt.sh --verify-only`。
細節見 [TensorRT 安裝與驗證](docs/installation.md#tensorrt-安裝與驗證) 和
[x86 效能紀錄](docs/x86-performance.md)。

## 首次設定

**管理者密碼（必要）**：在場域主機執行一次。輸入不顯示，只把 scrypt hash 存到
已排除 Git、權限 0600 的 `config/admin.env`；重新執行即更換密碼並登出所有人。
未設定時，控制台的管理 API 一律回 503。

```bash
uv run python scripts/configure-admin.py
```

**LLM 端點**：可用的端點只能在 `config/config.yaml` 的 `llm.endpoints` 編輯，
每個端點明確指定 `provider`（`llamacpp`／`ollama`／`openai`）、`base_url` 與
`api_key`。金鑰只會送往該端點自己的網址；控制台與數位人設定檔只能選端點名稱。
預設提供 `llamacpp`（`127.0.0.1:8080`，預設選用，後端自行啟動 llama-server）與
`ollama`（`localhost:11434`，選用時才需要 Ollama 與其模型）。預設不需要 11434 的
Ollama，停用方式見[安裝流程](docs/installation.md#停用預設-ollama11434)。

**以主機名稱連入**：除 `localhost` 與 IP 外，其他 `Host` 一律拒絕（防 DNS
rebinding）。管理者要用 `venue-pc.lan` 這類名稱連入時，先加入 `app.allowed_hosts`。

**參考音訊**：GPT-SoVITS、CosyVoice 等引擎的參考音訊要先在控制台「語音」設定的
音訊庫上傳（60 秒、20 MB 內，轉存為 WAV），再從清單選擇；刪除會移入回收桶，
使用中的音訊不能刪除。模型目錄只能從 `models/` 掃描結果選擇，TTS 服務只接受
本機位址。舊設定中的路徑在載入時會遷移進音訊庫，無法遷移的會清空並記錄警告。

**BreezyVoice（台灣華語）**：在 CosyVoice 的 conda 環境安裝
`python -m pip install --no-deps g2pw==0.1.1`，再執行
`uv run --no-sync python scripts/breezyvoice_weights.py` 把權重與 g2pW 下載到
`models/BreezyVoice`（固定版本並核對 SHA-256）。參考錄音須在 8 秒內，上傳音訊庫時
一併填寫與錄音逐字相同的逐字稿，並須是自錄或有書面授權的聲音；BreezyVoice 不串流，
每個回覆片段整段合成。與 MuseTalk、LLM 共用 RTX 4090 時第一個片段約需 2.5 s
（P50），額外顯存峰值約 5.9 GB，因此尚未取代 Edge TTS 成為預設。

**Edge TTS**：設定檔預設的語音引擎，只供開發。它使用非公開的微軟端點，沒有正式
商用授權，場域斷網時無法發聲；正式部署前須換成本機 TTS。

**天氣工具**：使用中央氣象署 CWA，授權碼只從服務端的 `NOVA_CWA_API_KEY`（亦支援
`CWA_API_KEY`）或已排除 Git 的 `config/cwa.env` 載入；可執行
`uv run python scripts/configure-cwa.py` 隱藏輸入。

## 啟動與使用

在專案根目錄執行：

```bash
bash scripts/start-all.sh
```

此命令先建置前端（`web/dist`），再啟動後端；控制台與舞台都由後端（埠 8010）
同源提供。後端日誌在 `logs/start-all-backend.log`；按 `Ctrl+C` 停止 Nova 與這次
帶起的 RAGFlow。

| 入口 | 預設位址 | 用途 |
| --- | --- | --- |
| 控制台 | `https://localhost:8010` | 對話、設定、語音驗證；區網以主機 IP 或 `allowed_hosts` 名稱連入 |
| 數位人舞台 | `https://localhost:8010/stage.html` | 訪客畫面，僅限場域主機本機 |
| 健康檢查 | `https://localhost:8010/health` | 確認後端就緒，不需登入 |
| RAGFlow 管理頁 | `http://127.0.0.1:8088` | 建立知識庫、上傳與解析文件，僅限本機 |

上表依預設的 `app.ssl: true`；關閉 SSL 時改用 HTTP，但管理者登入 cookie 需要
HTTPS，區網連入請保持開啟。

### 存取規則

路由分類集中在 `src/server/access.py`，每條路由都必須屬於一類：

- **管理**：控制台的所有 API 需管理者登入，本機也不例外；跨來源的變更請求一律拒絕。
- **舞台**：舞台設定、`/offer` 與舞台工作階段的 API 只接受場域主機本機
  （loopback）；其他電腦開啟舞台會得到 403。
- **公開**：`/health` 與前端靜態檔。

後端只提供 `web/dist`，缺少時啟動失敗並提示先執行 `npm run build`；不提供 CORS。
設計理由見 [ADR 0021](docs/adr/0021-stage-local-console-login.md)。

### RAGFlow 與程序管理

- 執行過 `ragflow.sh prepare` 的主機會一併啟動 RAGFlow，就緒後才啟動 Nova；
  尚未 `prepare` 的主機會略過。若 RAGFlow 已由其他命令啟動，會沿用該實例。
- Docker 未運行時會自動啟動，需要時在同一終端提示 `sudo` 密碼。Docker 或
  RAGFlow 啟動失敗（含 `sudo` 驗證失敗、等待逾時）只顯示警告，數位人照常啟動，
  只是暫無知識庫檢索。
- 暫時不啟動檢索：`NOVA_START_RAGFLOW=0 bash scripts/start-all.sh config/config.yaml`。
- 啟動腳本只停止本專案殘留的 Nova 程序（舊後端、Vite 開發伺服器、孤兒 CosyVoice），
  先送 SIGTERM，`NOVA_STOP_GRACE_SECONDS`（預設 20 秒）後才強制終止。埠
  8010／3000 被其他程式占用時報錯退出，不會誤殺。

### 分開啟動與前端開發

- 建置前端：`bash scripts/start-frontend.sh config/config.yaml`
- 啟動後端：`bash scripts/start-backend.sh config/config.yaml`
- RAGFlow：`bash scripts/ragflow.sh up`／`down`
- 前端開發：`bash scripts/start-frontend.sh --dev config/config.yaml`（或在 `web/`
  執行 `npm run dev`）。Vite 只綁 `127.0.0.1:3000` 並代理 API 到後端，不作正式入口。

設定檔路徑可為相對（以目前目錄為準）或絕對路徑。

### 場域 kiosk

場域主機要讓訪客直接使用舞台時，在 Nova 啟動後執行：

```bash
bash scripts/start-kiosk.sh
```

- 以 Chrome／Chromium 全螢幕開啟 `https://localhost:8010/stage.html?kiosk=1`，
  使用獨立設定檔 `.local/kiosk-profile`，預先放行聲音播放。
- 麥克風只對舞台來源放行，其他網站一律封鎖；權限寫在該設定檔，不影響主機上的
  其他 Chrome 設定檔。
- 使用自簽 localhost 憑證時，腳本以 `--allow-insecure-localhost` 只對 localhost
  接受；改用 mkcert 等受信任憑證後不再需要。
- 舞台看到 `kiosk=1` 會自動連線；連線逾時或中斷時依 2、3、5、8、10 秒退避自動
  重連，訪客只看到簡短提示。一般瀏覽器開啟 `/stage.html` 仍是點一下進入。
- `NOVA_KIOSK_URL`、`NOVA_KIOSK_BROWSER`、`NOVA_KIOSK_PROFILE` 可覆寫網址、
  瀏覽器與設定檔位置；麥克風只放行 `NOVA_KIOSK_URL` 的來源。

## 使用控制台

啟動後登入控制台，選擇數位人與模型，以文字或麥克風開始對話。控制台連線後，
點擊快捷指令會切回對話模式並立即送出；尚未連線或角色轉場中會保留問題並顯示提示。
舞台允許麥克風後即依免持模式收音；麥克風不可用時仍可使用文字輸入。

控制台與舞台各自對話，沒有訪客／控制台測試切換，也不互播問答。兩端各自保有
目前角色、記憶、語系、附件、字幕與影音；停止、返回、角色交接及斷線不影響另一端。
控制台按麥克風才收音，舞台保留免按對話。若兩頁都開啟同一實體麥克風，兩場對話
仍可能收到相同聲音。

### 角色設定與即時交接

「系統設定中心 → 數位人、AI 與知識設定」集中管理身分 Prompt、LLM 端點、回覆模式、
看板規則、RAG 知識庫與指定文件，以及聲音和工具。

- 先從設定檔清單選擇要編輯的數位人；切換設定檔會保留各自未儲存的草稿。共用人物
  素材的角色仍有各自的知識範圍。
- 「角色組合、交接與轉場」選主數位人及專門數位人，設定交接規則、說明與各方向轉場。
- 設定保存在 `config/avatar_profiles.yaml`。首次啟動會將現有有效設定複製為主角色；
  舊設定缺少的欄位只遷移一次，不覆蓋之後的修改。
- 「僅儲存草稿」不改變目前對話；「儲存並套用」更新之後的新對話，既有對話維持原設定。
  舞台在完整重置或重新連線後採用新設定；需要重載的共用資源會顯示待套用，等兩端
  斷線後更新。關閉交接時使用主數位人的完整設定檔。

首版即時組合使用兩位 MuseTalk 數位人，共用同一 LLM 端點、模型與語音合成引擎，
聲線可不同。主角色依交接規則判斷接手主題，播完交接說明後轉場，專門角色回答原問題；
舞台及控制台可返回主角色，WebRTC 連線與各角色記憶會保留。

- 在天氣助手時詢問非天氣問題，會先播反向交接說明與返回轉場，再由主數位人回答。
  一句話同時包含天氣與其他主題時，會先確認優先主題。反向交接的中英文文案可在同頁
  編輯。
- 去程、回程可選淡入淡出、左右滑動、縮放，或上傳 MP4／MOV／WebM 轉場影片
  （100 MiB、30 秒內）。影片會完整驗證並轉為靜音、25 fps，共同輸出為 720×1280，
  保留原比例及共用背景。
- 天氣助手提供目前觀測與未來七天預報，降雨機率只使用來源的前三天資料。角色設定可
  指定場域縣市與鄉鎮；留白且訪客未提供地點時會先詢問。可直接問「今天台北天氣如何？」
  這類縣市範圍問題；缺值、過舊或查詢失敗會明確說明。

驗證已啟用的角色組合（使用合成測試語音，不保存原始音訊或對話）：

```bash
uv run python scripts/run_role_soak.py --turns 50 --output .scratch/live-avatar-switch/role-soak.json
```

此工具以真實 WebRTC 收送音畫，量測舞台與控制台各自的交接；瀏覽器端的音畫順序與
嘴型仍需另外驗收。

### 對話記憶、雙語與附件

- 「對話記憶與語系」位於「系統設定中心」，也可由控制台工具列的「對話設定」開啟。
  可按角色檢視記憶與 Context、設定每場保留上限，以及中英文舞台與角色聲音。
- 對話、朗讀與語音驗證各自使用完整工作區，切換時保留草稿與測試狀態。
- PDF／圖片問答需由管理者套用相容的本機視覺模型；既有 Qwen 不會自動被替換。
- 控制台與舞台各自依閒置時間清場：預設 15 秒清字幕與看板，60 秒清空本場各角色
  記憶、附件與草稿並回主角色。上傳、分析與回答期間暫停計時，一端清場不影響另一端。
- 舞台完全空場後等待 30 秒才準備閒置招呼；招呼、舞台文字輸入與 RAGFlow 模型統一
  服務都須明確啟用。

詳見 [附件操作、模型與生命週期](docs/conversation-attachments.md)、
[閒置招呼](docs/idle-greetings.md) 和
[本次 PC 實測與驗證範圍](.scratch/jetson-to-pc-port/validation/README.md)。

## RAGFlow 文件檢索（選用）

RAGFlow 使用獨立的 Docker Compose 專案、資料卷，以及主機上的 CPU 嵌入服務。需要
Docker、Compose 2.40 以上、使用者層級 systemd 和 Ollama。部署腳本固定取得 RAGFlow
`v0.27.2`，管理頁與 API 只開放在本機。未完成此節時，一般對話仍可使用。

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
   `NOVA_RAGFLOW_URL=http://127.0.0.1:9380`。啟動腳本只把這份檔案載入後端。
6. 重啟 Nova 後端。在「設定 → 數位人、AI 與知識設定」選定數位人，開啟「RAG 知識
   文本」確認顯示「RAGFlow 已連線」，選知識庫與文本範圍、按「測試目前草稿」，
   再啟用檢索並「儲存並套用」。

RAGFlow 故障或逾時時，Nova 繼續一般回答並在控制台顯示狀態；沒有命中時照常回答，
不宣稱具有文件依據。檢索片段只是參考預覽，不代表正式引文。檢索設定依數位人設定檔
分開保存，初始為關閉；非機密設定存於 `config/ragflow_settings.yaml`。

推送到 GitHub 前，確認金鑰與 RAGFlow 密碼仍只在本機：

```bash
git status
git check-ignore -v config/ragflow.env .local/ragflow
git diff --cached
```

`config/ragflow.env` 必須顯示為 ignored；暫存區不得出現金鑰、管理密碼或
`.local/ragflow/`。`config/ragflow.env.example` 只保留空白欄位。若金鑰曾進入版本庫，
先在 RAGFlow 撤銷並重建，再從 Git 歷史移除。建置步驟、隔離、故障說明與驗證清單見
[RAGFlow 本機檢索整合](docs/ragflow.md)。

## 設定與檢查

`config/config.yaml` 設定服務埠、SSL、允許的主機名稱、Avatar、VAD、STT、LLM 端點、
TTS、字幕與回覆模式；控制台可調整常用選項，並寫入 `config/runtime_overrides.yaml`
（優先於 `config.yaml`）。切換 Avatar、STT 或 TTS 引擎前，先中斷目前 WebRTC 會話。

開發與交付檢查與 [CI](.github/workflows/ci.yml) 相同：

```bash
uv sync --inexact --group dev --extra vad --extra musetalk
# 已啟用 TensorRT 時，同步依賴加上 --extra tensorrt。
uv lock --check
uv run ruff check .
uv run pyright
uv run python scripts/check-integration.py
uv run pytest
cd web
npm ci
npm run lint
npm test
npm run build
```

- ruff 含安全與 async 規則（例如 `requests` 必須設 timeout、async handler 內不得
  阻塞）；pyright 檢查 `src/server` 的未綁定變數。
- ESLint 禁止新增 `v-html`，並涵蓋 `stage.html`。
- `tests/test_route_access.py` 要求每條路由都在 `src/server/access.py` 分類。
- 測試不得寫入專案的 `data/`。

`check-integration.py` 預設執行離線檢查；備妥設定檔指定的 LLM 與 Edge TTS 後，可用
`--smoke` 檢查實際服務。真實 WebRTC 語音回合的首音延遲以
`scripts/measure_first_audio.py` 量測（需關閉舞台頁，只在場域主機本機執行），
驗證方式見[目前專案基線](docs/project-status.md)；x86 影音排程與效能見
[x86 即時效能優化](docs/x86-performance.md)。審查規則見
[CODING_STANDARDS.md](CODING_STANDARDS.md)。

## 授權與來源

Nova Avatar 自行撰寫的程式採 [Apache-2.0](LICENSE)。MuseTalk 程式採 MIT 授權；
模型、權重與依賴另有條款。內含 Wav2Lip 整合僅供 **Research / Non-commercial**
使用，不得視為可商用。RAGFlow、BGE-M3、語音、資料集與外部服務也須各自核對條款；
根目錄授權不會擴及它們。詳見 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)、
[NOTICE](NOTICE) 和 [軟體組合](docs/software-stack.md)。
