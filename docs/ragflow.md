<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# RAGFlow 本機檢索整合

Nova Avatar 只向 RAGFlow 查找文件片段，並由 Nova 現有的模型、回覆規則、字幕、
語音與看板流程產生、交付回答。RAGFlow 使用獨立的 Compose 專案與資料庫；
完成本機準備後，`scripts/start-all.sh` 會一併啟動它。嵌入服務是只用 CPU 的
llama.cpp `llama-server --embedding`（使用者層級服務
`nova-ragflow-llamacpp-embedding.service`），載入 `models/ragflow/bge-m3-f16.gguf`
（與 Ollama `bge-m3:latest` 同一份權重，sha256 固定），不占 GPU 顯存；查詢嵌入
約 0.05 s，RAGFlow 檢索端到端約 0.1 s。執行檔預設依序找 `PATH` 上的
`llama-server` 與 `~/llama/llama.cpp/build/bin/llama-server`，可用
`NOVA_RAGFLOW_LLAMA_SERVER` 指定；執行緒數預設 4（`NOVA_RAGFLOW_EMBEDDING_THREADS`）。
不需要系統的 11434 Ollama 服務（`pull-model` 首次取得權重等例外見
[停用預設 Ollama](installation.md#停用預設-ollama11434)）；Nova 自己的 llama.cpp
語言模型服務（8080）不變。首次安裝與每位數位人的檢索設定均預設關閉。

## 本機安裝

若主機尚未安裝 Docker，安裝套件需要主機使用者在終端輸入自己的 `sudo`
密碼；不要在聊天中傳送密碼。Ubuntu 24.04 可執行：

```bash
bash scripts/ragflow.sh install-docker
bash scripts/ragflow.sh prepare
bash scripts/ragflow.sh validate
bash scripts/ragflow.sh pull-model
bash scripts/ragflow.sh up
bash scripts/ragflow.sh status
```

若安裝後 `docker info` 顯示群組權限錯誤，請重新登入本機 shell，再從 `validate`
繼續。`prepare` 會在忽略版本控制的 `.local/ragflow/upstream` 取得固定的
RAGFlow `v0.27.2`，並產生檔案權限 `0600` 的獨立隨機密碼；重跑不會覆蓋現有
密碼。RAGFlow 映像以 tag 加 digest 固定（`validate` 會拒絕不符者，既有設定
重跑 `prepare` 時只更新映像欄位）；`pull-model` 以 Ollama 取得 BGE-M3，驗證權重
blob 的 sha256 後複製為唯讀的 `models/ragflow/bge-m3-f16.gguf` 並再次驗證，主機
現有或新拉取的版本不符即中止。GGUF 已存在且通過驗證時直接沿用，不需要 Ollama；
存在但內容不符時保留原檔並中止，請移到他處後重跑。`up` 啟動 `nova-ragflow`
Compose 專案與 llama.cpp 嵌入服務；`down` 停止兩者，但不刪除資料卷或模型。
首次拉取映像、模型及建立索引可能需要較長時間和磁碟空間。

首次設定完成後，可用 `bash scripts/ragflow.sh down` 停止手動啟動的服務；
日常執行 `bash scripts/start-all.sh config/config.yaml` 時會自動重新啟動。
也可直接執行 `bash ./scripts/start-all.sh` 使用預設設定。已安裝的 Docker
尚未運行時，腳本會先啟動本機 Docker 服務，必要時在同一終端要求 `sudo`
驗證；Docker 已就緒時不會要求管理權限。遠端 Docker context 或 rootless
服務仍由其原本的方式管理。啟動後會等待容器健康狀態、RAGFlow 網頁、
API 與獨立嵌入端點就緒，再啟動 Nova 前後端。Docker 無法啟動或 RAGFlow
逾時只顯示警告，並停止這次帶起的部分服務；數位人照常啟動，暫無知識庫檢索。
`NOVA_RAGFLOW_STARTUP_TIMEOUT` 可調整容器與端點各自的等待上限（預設 180 秒）。
若 RAGFlow 在啟動 Nova 前已經執行，`start-all.sh` 會沿用它，按 `Ctrl+C`
也不會停止該既有實例；若由 `start-all.sh` 帶起，則在結束時停止。
Docker 啟動時自動恢復的既有容器也會沿用；退出 Nova 不會停止 Docker 本身。
`NOVA_START_RAGFLOW=0` 可暫時略過自動啟動。尚未執行 `prepare` 的主機
直接啟動 Nova 時，RAGFlow 會被略過。

每輪主回答最多等檢索 0.3 s（`RETRIEVAL_BUDGET_SECONDS`，見 ADR 0022）；逾時時
Nova 標示本輪未取得檢索並繼續原本回答，不會把未取得的文件當作依據。匯入後請先在
控制台使用「測試檢索」確認命中，再啟用數位人的 RAG。

文件解析也在 CPU 上嵌入，比查詢慢得多：4 執行緒約每 1,000 token 5 秒（512 token
的預設切片約 2.5 秒），請在低流量時段匯入。BGE-M3 一段輸入須一次算完，伺服器上限
2,048 token；超過的切片會解析失敗，請維持預設切片大小（512）或不超過 2,048。
上限與記憶體相關：2,048 token 的切片峰值約 3.5 GB，服務記憶體上限 4 GB。

部署使用官方 Compose 與 Nova 疊加設定。生效服務為 RAGFlow、Elasticsearch、
MySQL、MinIO、Redis。只有 RAGFlow 網頁
`http://127.0.0.1:8088` 和 API `http://127.0.0.1:9380` 發布至主機
loopback；其他容器只在 Compose 網路上。嵌入程序只綁定 Docker 本機橋接位址
的 `11437`，RAGFlow 容器透過 `host.docker.internal` 存取；它與先前的 Ollama
一樣不驗證金鑰（RAGFlow 的 OpenAI 用戶端要求非空金鑰，因此登記為 `x`），也不提供
網頁介面。RAGFlow、搜尋引擎和嵌入程序設有 CPU／記憶體上限（嵌入程序
`CPUQuota=400%`、`MemoryMax=4G`，不使用 GPU），文件批量解析降至一次一份。即使如此，
解析大量文件仍可能爭用 CPU、磁碟與記憶體；應在低流量時段匯入，並實測對話延遲。

## 建立知識庫與連接 Nova

1. 在這台主機開啟 `http://127.0.0.1:8088`，建立 RAGFlow 管理帳號，
   立即更改初始密碼。初始管理密碼保存在忽略版控的
   `.local/ragflow/upstream/docker/.env` 中 `ADMIN_DEFAULT_PASSWORD` 欄位。
2. 執行 `bash scripts/ragflow.sh connect`：建立或沿用 Nova 的 API 金鑰（無法
   自動建立時改用第 3–4 步手動建立後重跑），並在 RAGFlow
   登記 `OpenAI-API-Compatible` 供應者的 `nova-llamacpp` 執行個體（服務位址
   `http://host.docker.internal:11437/v1`、嵌入模型 `bge-m3`、上限 2,048 token），
   尚無預設嵌入模型時設為預設。RAGFlow 登記前會實際呼叫一次嵌入服務，請先
   `up`。要手動登記時，在 RAGFlow 模型供應者設定填相同的值，API 金鑰填 `x`。
   建立知識庫前，請核對模型卡與權重授權。
3. 在 RAGFlow 建立知識庫，上傳文件、完成解析。文件上傳／解析只在
   RAGFlow 原生介面管理。接著點右上角頭像 → 設定 → **API** 頁，
   建立並複製 API 金鑰。
4. 複製 `config/ragflow.env.example` 為 `config/ragflow.env`，設定
   `NOVA_RAGFLOW_API_KEY`，並執行 `chmod 600 config/ragflow.env`。
   `scripts/start-all.sh` 和 `scripts/start-backend.sh` 只把這份檔案載入後端
   環境。`config/ragflow.env.example` 的金鑰欄位必須留空。金鑰不得寫進
   控制台、`runtime_overrides.yaml`、README 或版本庫。
5. 啟動或重啟 Nova 後端。於控制台「設定 → 知識庫檢索」頁查看連線狀態，為目前數位人選擇
   知識庫並啟用。先用「測試檢索」確認能找出相關片段，再試文字與語音各一輪。
   設定從下一輪生效。

本機以外的瀏覽器無法直接開啟 loopback 的 RAGFlow 管理頁。需遠端管理時，
可在信任的連線上使用 SSH 埠轉送；不要直接把管理埠對外開放。

## 行為與隔離邊界

- 目前只有一位數位人，但設定仍以 `avatar_id` 為鍵分開保存。此角色的啟用
  與知識庫選擇不會成為未來新增角色的預設值。每輪開始時快照目前角色設定；
  切換角色後的下一輪重新選取，不會沿用前一角色的檢索片段。
- 每輪最多取 4 段、每段最多 800 字；檢索總逾時 8 秒（依當時 CPU BGE-M3
  實測由原先 2.5 秒調整）。檢索資料只放進
  本輪模型上下文，不寫進對話歷史。控制台的「檢索參考」只是片段預覽，
  不是正式引文，也不另行送入語音或看板。
- 沒有命中時照常一般回答，不在語音或控制台對話加註；檢索狀態只記錄在
  `rag_retrieval` 事件。服務停用、逾時或故障時，繼續原本回答流程，控制台
  顯示失敗狀態。兩種情況都不得把一般回答表示成有文件依據。
- 無命中與服務失敗是不同狀態：前者代表服務正常但找不到相關片段，後者代表
  檢索本身沒有完成。
- 檢索片段是參考資料，不是系統指令；文件內容不得覆寫 Prompt 或回覆規則。
- 各數位人的知識庫選擇是**功能路由，不是存取控制**。Nova 現有控制台與
  API 若對不可信網路開放，必須另行加入認證／授權，才可存放私密文件。
- `bash scripts/ragflow.sh down` 不會刪除文件和資料卷。不要用
  `docker compose down -v`，除非已確認要永久刪除知識庫資料。

## 驗證清單

先用少量、有明確答案的文件驗證切分與檢索品質，再擴充資料量。每次更換文件
或檢索設定後，至少確認：

| 情境 | 預期結果 |
| --- | --- |
| 已知答案 | 「測試檢索」命中預期文件，回答內容符合片段 |
| 改寫問題 | 不使用文件原句也能找到相同內容 |
| 無答案問題 | 一般回答，不捏造文件來源 |
| 版本衝突的文件 | 能從文件名稱或 metadata 分辨版本 |
| 含命令的文件片段 | 片段內的指示不能覆寫系統規則 |
| RAGFlow 停止 | 控制台標示失敗，對話照常完成 |
| 切換數位人 | 不沿用前一位角色的片段或知識庫選擇 |
| 文字與語音 | 兩種入口各完成一輪 |

RAGFlow 與 BGE-M3 是第三方元件，相關來源與授權界限見
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)。

## 從 GPU Ollama 嵌入切換到 llama.cpp

2026-10-30 以前的部署以 `nova-ragflow-embedding.service`（GPU 上的 Ollama，
`11435`）提供嵌入，每次查詢約 0.5 s，並常駐約 1.6 GB 顯存。已有知識庫的主機：

```bash
bash scripts/ragflow.sh pull-model        # 驗證並複製 GGUF（不必重新下載）
bash scripts/ragflow.sh up                # 啟動 llama.cpp 嵌入服務
bash scripts/ragflow.sh switch-embedding
```

`switch-embedding` 依序：

1. 把所有知識庫、其文件清單與預設模型存到 `.local/ragflow/backups/embedding-switch-*.json`
   （權限 `0600`）。
2. 登記 `nova-llamacpp` 執行個體（同 `connect`）。
3. 對每個使用 BGE-M3 且已有切片的知識庫，以 RAGFlow 的
   `/datasets/<id>/embedding/check` 比對已存向量與新服務的向量；最小餘弦低於
   0.99 即中止，不改任何設定。兩邊是同一份權重，實測為 1.0，所以不重新解析、
   不刪除文件；使用其他嵌入模型的知識庫不動。
4. 把這些知識庫與租戶預設嵌入模型改為 llama.cpp 的 BGE-M3。
5. 經每個知識庫各做一次檢索；全部成功才停用 `nova-ragflow-embedding.service`。
   單元檔保留在 `integrations/ragflow/` 供還原。

停用後，RAGFlow 裡掛在舊 Ollama 執行個體（`11435`）上的聊天模型也無法使用；Nova
只用 RAGFlow 檢索，不受影響。需要 RAGFlow 自己的聊天功能時，改用
`connect-chat` 或下一節的 `unify-models`（走主機 11434 的 Ollama）。

### 還原為 GPU Ollama 嵌入

1. 重新啟用舊服務並確認就緒：

   ```bash
   systemctl --user link "$PWD/integrations/ragflow/nova-ragflow-embedding.service"
   systemctl --user enable --now nova-ragflow-embedding.service
   curl --noproxy '*' -fsS "http://$(docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}'):11435/api/tags"
   ```

2. 在 RAGFlow 網頁把知識庫的嵌入模型改回備份中的原值（備份檔
   `datasets[].embedding_model` 與 `embedding_model_name`，例如
   `bge-m3:latest@bge-m3@Ollama`），並在模型供應者設定把預設嵌入模型改回備份中
   `defaults` 的 `embedding` 項。兩邊向量相同，不必重新解析文件。
3. 確認「測試檢索」命中後，可停用 llama.cpp 嵌入服務：
   `systemctl --user disable --now nova-ragflow-llamacpp-embedding.service`。
   之後 `up` 仍會啟動它（只用 CPU，閒置時不耗資源）；要長期還原，`up` 後再停用一次。
4. 把 `src/server/voice_session.py` 的 `RETRIEVAL_BUDGET_SECONDS` 改回 0.7，
   否則約 0.5 s 的 GPU Ollama 檢索幾乎每輪逾時。

## PC 與主機 Ollama 模型統一（選用）

此移植保留既有獨立服務；不會自動改變工作區、知識庫或預設模型。
管理者明確執行以下命令才啟用共用服務：

```bash
bash scripts/ragflow.sh unify-models
# 之後立即同步新下載的模型
bash scripts/ragflow.sh sync-models
```

只統一聊天模型：RAGFlow 的 Ollama 聊天模型改經
`http://host.docker.internal:11436`，透過本機 Docker bridge 轉送至主機 Ollama
（11434）；嵌入仍由 llama.cpp 提供。仍有知識庫使用 Ollama 嵌入時拒絕執行，請先
`switch-embedding`。舊 GPU 嵌入服務上的執行個體會改指向轉送位址，保留其中的
聊天模型。主機既有 Ollama 仍由原服務管理。背景同步每 30 秒只加入新的聊天模型
（不加入僅供嵌入的模型），不刪模型、不改管理者已選預設。`connect-chat` 同樣只
登記聊天模型。`up`／`down` 同時管理已啟用的轉送與同步服務；本次不搬 Jetson 的
資料卷。共用模式的 GPU 駐留由主機 Ollama 管理，須與即時數位人及 STT 一起評估。
