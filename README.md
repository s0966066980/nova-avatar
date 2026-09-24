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

架構與已驗證的執行邊界見 [數位人與場景架構](docs/avatar-scene-architecture.html)、
[目前專案基線](docs/project-status.md) 和
[軟體組合](docs/software-stack.md)。

## 安裝 Nova Avatar

以下以 Linux、MuseTalk 和預設 `config/config.yaml` 為例。需要 Python
3.10／3.11、[uv](https://docs.astral.sh/uv/)、Node.js／npm、FFmpeg，以及
設定檔指定的 Ollama 或 llama.cpp 模型服務。MuseTalk 需要 NVIDIA GPU、相容
的 CUDA 環境與權重；安裝腳本編譯 mmcv 時可能需要 CUDA Toolkit 12.4。

```bash
git clone https://github.com/s0966066980/nova-avatar.git
cd nova-avatar
bash scripts/setup-env.sh musetalk
source .venv/bin/activate
bash scripts/download_musetalk_weights.sh
bash scripts/create_ssl_certs.sh
```

`setup-env.sh` 會安裝 Python、Avatar 與前端依賴；若 `.venv` 已存在，會詢問
是否重建。權重下載後請檢查腳本列出的模型檔是否齊全。預設 YAML 啟用 SSL，
因此首次啟動前需建立憑證。若改用其他 Avatar，請先核對其依賴和授權。

預設 LLM 設定使用本機 Ollama 的 `qwen3.5:4b`；請先啟動 Ollama 並備妥
該模型，或在 `config/config.yaml` 改成可用的模型與服務位址。Avatar、
STT、TTS、回覆模式也可在控制台設定。只安裝核心依賴時可改用：

```bash
uv venv --python 3.10.19
uv sync --extra vad
cd web && npm install && cd ..
```

選用 MuseTalk 時請依前述 `setup-env.sh musetalk` 完成其 CUDA／OpenMMLab
依賴。之後同步依賴應保留 `--extra musetalk`，避免移除相關套件。

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

6. 重啟 Nova 後端。在控制台「設定 → 知識庫檢索」確認顯示「RAGFlow 已連線」，
   為目前數位人選知識庫、先「測試檢索」，再啟用。設定從下一輪生效。

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

先閱讀圖形化的 [基礎 RAG 圖解與建置指南](docs/ragflow.html)，更完整的行為、
隔離與故障說明見 [RAGFlow 本機檢索整合](docs/ragflow.md)。

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
需要文件檢索時，到「設定 → 知識庫檢索」檢查連線、勾選知識庫並儲存，
先按「測試檢索」確認有相關片段，再開啟該數位人的檢索。設定從下一輪
對話生效。無命中時會標明回答沒有文件依據；RAGFlow 故障或逾時時，
Nova 繼續一般回答並在控制台顯示狀態。檢索片段只是參考預覽，
不代表正式引文。檢索設定依數位人分開保存，初始為關閉。

如需分開啟動 Nova 前後端，可在不同終端執行
`bash scripts/start-backend.sh config/config.yaml` 和
`bash scripts/start-frontend.sh config/config.yaml`；RAGFlow 則以
`bash scripts/ragflow.sh up`／`down` 獨立管理。

## 設定與檢查

`config/config.yaml` 設定服務埠、SSL、Avatar、VAD、STT、LLM、TTS、
字幕與回覆模式；控制台可調整常用選項。切換 Avatar、STT 或 TTS 引擎前，
先中斷目前 WebRTC 會話。RAGFlow 的非機密角色設定另存於
`config/ragflow_settings.yaml`；API 金鑰留在 `config/ragflow.env`。

開發與交付檢查：

```bash
uv sync --group dev --extra vad --extra musetalk
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

## 授權與來源

Nova Avatar 自行撰寫的程式採 [Apache-2.0](LICENSE)。MuseTalk 程式採
MIT 授權；模型、權重與依賴另有條款。內含 Wav2Lip 整合僅供
**Research / Non-commercial** 使用，不得視為可商用。RAGFlow、BGE-M3、
語音、資料集與外部服務也須各自核對條款；根目錄授權不會擴及它們。
詳見 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)、
[NOTICE](NOTICE) 和 [軟體組合](docs/software-stack.md)。
