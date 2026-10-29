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
uv、MuseTalk 權重、RAGFlow 映像與 BGE-M3 均固定版本並驗證 checksum／digest，
不符即中止；控制台的 Bootstrap 與圖示由 npm 套件打包，場域斷網時仍可顯示。

### 管理者裝置信任本機 CA（只需一次）

主機已安裝 [mkcert](https://github.com/FiloSottile/mkcert) 時，SSL 腳本優先
以它建立本機 CA 簽發的憑證，涵蓋 `localhost`、主機名稱與區網 IP（可在指令後
追加其他名稱，例如 `bash scripts/create_ssl_certs.sh nova.lan`）：

1. 在主機執行 `mkcert -install`，讓本機舞台瀏覽器信任此 CA。
2. 將 `$(mkcert -CAROOT)/rootCA.pem` 複製到每台管理者裝置，匯入系統或瀏覽器的
   「受信任的根憑證」。之後重新簽發憑證不必再匯入。
3. 切勿複製 `rootCA-key.pem`；它只留在主機上。

未安裝 mkcert（或設定 `NOVA_SSL_SELF_SIGNED=1`）時改產生自簽憑證，瀏覽器
首次連線需手動接受警告。

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

首次啟動前，先在場域主機設定控制台管理者密碼（隱藏輸入，只保存 scrypt
hash 於已排除 Git、權限 0600 的 `config/admin.env`；重新執行即更換密碼並
登出所有人）：

```bash
uv run python scripts/configure-admin.py
```

未設定密碼時，控制台的管理 API 一律回 503，後端日誌會提示執行上述腳本。

在專案根目錄執行：

```bash
bash ./scripts/start-all.sh
```

此命令先建置前端（`web/dist`），再啟動後端；控制台與舞台都由後端
（埠 8010）同源提供，不另開前端伺服器。執行過 `ragflow.sh prepare` 的主機會一併
啟動 RAGFlow；尚未執行 `prepare` 的主機會提示略過 RAGFlow，繼續啟動 Nova。
若已安裝的 Docker 尚未運行，啟動腳本會自動啟動它；需要管理權限時，
直接在同一個終端提示輸入 `sudo` 密碼。RAGFlow 的容器、網頁、API 與嵌入
服務就緒後，才會啟動 Nova 前後端，不必另開終端逐一啟動服務。Docker 或
RAGFlow 啟動失敗（含 `sudo` 驗證失敗、等待逾時）只會顯示警告並收掉這次
帶起的部分服務，數位人照常啟動，只是暫無知識庫檢索。
若 RAGFlow 已由其他命令啟動，`start-all.sh` 會沿用該實例。按
`Ctrl+C` 停止 Nova，以及這次由 `start-all.sh` 帶起的 RAGFlow 服務；
既有 RAGFlow 實例會保持執行。暫時不啟動檢索服務可執行
`NOVA_START_RAGFLOW=0 bash scripts/start-all.sh config/config.yaml`。
首次安裝 Docker／模型及準備 RAGFlow 仍依下方安裝步驟進行。

| 入口 | 預設位址 | 用途 |
| --- | --- | --- |
| Web 控制台 | `https://localhost:8010` | 對話、設定、語音驗證；區網以主機 IP 連入 |
| 數位人舞台 | `https://localhost:8010/stage.html` | 獨立演播畫面，僅限場域主機本機 |
| 後端健康檢查 | `https://localhost:8010/health` | 確認 Nova 後端就緒 |
| RAGFlow 管理頁 | `http://127.0.0.1:8088` | 建立知識庫、上傳與解析文件 |

上表依預設 YAML 的 `app.ssl: true` 顯示 HTTPS；若關閉 SSL，Nova
控制台和後端網址改用 HTTP。RAGFlow 管理頁只綁定主機 loopback，從另一
台電腦無法直接連線。後端日誌在 `logs/start-all-backend.log`。

啟動腳本只會停止本專案殘留的 Nova 程序（舊後端、Vite 開發伺服器與孤兒
CosyVoice），先送 SIGTERM 讓其正常收尾，`NOVA_STOP_GRACE_SECONDS`（預設 20
秒）後仍未結束才強制終止；埠 8010／3000 被其他程式占用時會報錯退出，不會
誤殺。`start-all.sh` 讓後端自成程序群組，結束時連同子程序一併停止。

存取規則（路由分類集中在 `src/server/access.py`）：控制台需以管理者密碼
登入，本機也不例外；登入 cookie 為 `Secure`，區網連入請使用 HTTPS。
數位人舞台只在場域主機本機（loopback）開啟，其他電腦開啟會被拒絕（403）。
`/health` 與前端靜態檔不需登入。後端只提供 `web/dist` 建置結果，缺少時
啟動失敗並提示先執行 `npm run build`。後端不提供 CORS，跨來源的變更請求
一律拒絕。為防 DNS rebinding，只接受以 `localhost`、IP 或設定檔
`app.allowed_hosts` 列出的主機名稱連線；以主機名稱連入控制台前先加入該清單。

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
「儲存並套用」更新之後的新對話，既有對話維持原設定。舞台在完整重置或重新連線後採用新設定；需要重載的共用資源會顯示待套用，等兩端斷線後更新。關閉交接時同樣
使用主數位人的完整設定檔。重啟時會載入已儲存設定；舊設定缺少的回覆模式、
語意等待上限與看板項目上限會從現有有效設定遷移一次。

首版即時組合使用兩位 MuseTalk 數位人，共用同一 LLM 服務與模型，以及同一
語音合成引擎；聲線可不同。主角色依交接規則判斷接手主題，播完交接說明後轉場，
專門角色回答原問題。舞台及控制台可返回主角色，WebRTC 連線與各角色記憶會保留。
在天氣助手時詢問非天氣問題，會先播反向交接說明、播放返回轉場，再由
主數位人直接回答原問題。天氣相關生活建議與追問繼續由天氣助手處理；
一句話包含天氣與其他主題時，會先確認優先主題。反向交接的中英文文案
可在同一設定頁編輯；舊設定首次載入會補上預設文案，保留已設定內容。
控制台與舞台各自依閒置時間清場：預設 15 秒清字幕與看板，60 秒清空
本場各角色記憶、附件與草稿並回主角色。上傳、分析與回答期間暫停，
一端清場不清除另一端；對話記憶面板會顯示本場目前有效的時間。

去程、回程可各自選淡入淡出、左右滑動、縮放，或上傳 MP4／MOV／WebM
轉場影片（100 MiB、30 秒內）。影片會完整驗證，轉為靜音、25 fps；
共同輸出為 720×1280，保留原比例及共用背景。
控制台與舞台各自對話，沒有訪客／控制台測試切換，也不互播問答。兩端各自保有目前角色、記憶、語系、附件、字幕與影音；停止、返回、角色交接及斷線不影響另一端。控制台按麥克風才收音，舞台保留免按對話；舞台招呼與自動清場不清除控制台紀錄。若兩頁都主動開啟同一實體麥克風，兩場對話仍可能收到相同聲音。

控制台連線後，點擊快捷指令會切回對話模式並立即送出；尚未連線或角色
轉場中會顯示提示並保留問題。舞台進入後允許麥克風權限，即依免持模式
自動收音，開啟文字／附件功能也相同；麥克風不可用時仍可使用文字輸入。

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

場域主機要讓訪客直接使用數位人舞台時，在 Nova 啟動後執行：

```bash
bash scripts/start-kiosk.sh
```

腳本以 Chrome／Chromium 全螢幕開啟後端提供的 `https://localhost:8010/stage.html?kiosk=1`，
預先放行聲音播放，並使用獨立的瀏覽器設定檔 `.local/kiosk-profile`。麥克風只對
舞台來源（`https://localhost:8010`）放行，其他網站一律封鎖；權限寫在該設定檔，
不影響主機上其他 Chrome 設定檔。HTTPS 預設使用自簽 localhost 憑證，腳本以
`--allow-insecure-localhost` 只對 localhost 接受；改用受信任憑證時不再需要。舞台看到 `kiosk=1` 會自動
連線，連線中斷時依 2、3、5、8、10 秒退避自動重連，訪客只看到「數字人暫時無法使用」
這類簡短提示。一般瀏覽器開啟 `/stage.html` 不受影響，仍是點一下進入。
可用 `NOVA_KIOSK_URL`、`NOVA_KIOSK_BROWSER`、`NOVA_KIOSK_PROFILE` 覆寫網址、瀏覽器與
設定檔位置；麥克風只放行 `NOVA_KIOSK_URL` 的來源。

如需分開啟動 Nova，先以 `bash scripts/start-frontend.sh config/config.yaml`
建置前端，再以 `bash scripts/start-backend.sh config/config.yaml` 啟動後端；
RAGFlow 則以 `bash scripts/ragflow.sh up`／`down` 獨立管理。開發前端時可執行
`bash scripts/start-frontend.sh --dev config/config.yaml`（或在 `web/` 執行
`npm run dev`），Vite 開發伺服器只綁 `127.0.0.1:3000`、API 代理到後端，
不作正式入口。設定檔路徑可為相對（以目前目錄為準）或絕對路徑。

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

### PC：對話記憶、雙語與附件

PC 現在支援按角色檢視記憶與 Context、設定每場保留上限、中英文舞台及
角色聲音、PDF／圖片問答和選用的舞台文字輸入；保留角色交接，控制台與舞台各自對話。
附件需由管理者套用相容的本機視覺模型，既有 Qwen 不會自動被替換。

「對話記憶與語系」位於「系統設定中心」，也可由控制台工具列的「對話設定」
直接開啟，再按「返回控制台」回到原模式。控制台只保留目前角色與回覆語系摘要；
對話、朗讀與語音驗證各自使用完整工作區，切換時保留草稿與測試狀態。

舞台預設 15 秒清畫面、60 秒完整重置；完全空場後才等待 30 秒準備招呼。
招呼、舞台文字及 RAGFlow 模型統一服務均須明確啟用。

- [附件操作、模型與生命週期](docs/conversation-attachments.md)
- [RAGFlow 選用模型同步](docs/ragflow.md#pc-與主機-ollama-模型統一選用)
- [本次 PC 實測與驗證範圍](.scratch/jetson-to-pc-port/validation/README.md)
