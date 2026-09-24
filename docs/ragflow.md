<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# RAGFlow 本機檢索整合

Nova Avatar 只向 RAGFlow 查找文件片段，並由 Nova 現有的模型、回覆規則、字幕、
語音與看板流程產生、交付回答。RAGFlow 使用獨立的 Compose 專案與資料庫；
完成本機準備後，`scripts/start-all.sh` 會一併啟動它。嵌入服務沿用主機已安裝
的 Ollama 程式與 BGE-M3 模型檔，但另開一個使用 GPU 的程序（預設 CUDA 裝置 0，
可用 `NOVA_RAGFLOW_CUDA_VISIBLE_DEVICES` 覆寫）；Nova 原有的 Ollama 與
llama.cpp 語言模型服務不變。首次安裝與每位數位人的檢索設定均預設關閉。

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
密碼。`up` 啟動 `nova-ragflow` Compose 專案與獨立的使用者層級嵌入服務；
`down` 停止兩者，但不刪除資料卷或模型。首次拉取映像、模型及建立索引可能需要
較長時間和磁碟空間。

首次設定完成後，可用 `bash scripts/ragflow.sh down` 停止手動啟動的服務；
日常執行 `bash scripts/start-all.sh config/config.yaml` 時會自動重新啟動。
若 RAGFlow 在啟動 Nova 前已經執行，`start-all.sh` 會沿用它，按 `Ctrl+C`
也不會停止該既有實例；若由 `start-all.sh` 帶起，則在結束時停止。
`NOVA_START_RAGFLOW=0` 可暫時略過自動啟動。尚未執行 `prepare` 的主機
直接啟動 Nova 時，RAGFlow 會被略過。

首次匯入文件後的第一筆檢索可能比後續查詢慢；改用 GPU 前的 CPU 嵌入實測曾達約
31 秒，超過 Nova 的 8 秒檢索上限。此時 Nova 會標示檢索逾時並繼續原本回答，
不會把未取得的文件當作依據。匯入後請先在控制台使用「測試檢索」預熱並確認
命中，再啟用數位人的 RAG。

部署使用官方 Compose 與 Nova 疊加設定。生效服務為 RAGFlow、Elasticsearch、
MySQL、MinIO、Redis。只有 RAGFlow 網頁
`http://127.0.0.1:8088` 和 API `http://127.0.0.1:9380` 發布至主機
loopback；其他容器只在 Compose 網路上。嵌入程序只綁定 Docker 本機橋接位址
的 `11435`，RAGFlow 容器透過 `host.docker.internal` 存取。RAGFlow、搜尋
引擎和嵌入程序設有 CPU／記憶體上限（嵌入程序另會使用 GPU 顯存，需與
MuseTalk、STT 和語言模型一起估算），文件批量解析降至一次一份。即使如此，
解析大量文件仍可能爭用磁碟與記憶體；應在低流量時段匯入，並實測對話延遲。

## 建立知識庫與連接 Nova

1. 在這台主機開啟 `http://127.0.0.1:8088`，建立 RAGFlow 管理帳號，
   立即更改初始密碼。初始管理密碼保存在忽略版控的
   `.local/ragflow/upstream/docker/.env` 中 `ADMIN_DEFAULT_PASSWORD` 欄位。
2. 在 RAGFlow 模型供應者設定中新增 Ollama 執行個體：服務位址
   `http://host.docker.internal:11435`，嵌入模型 `bge-m3`。此嵌入程序
   與 Nova 的 `127.0.0.1:11434` 語言模型程序分開，但讀取同一份本機模型檔，
   不另下載 Ollama 映像。建立知識庫前，請核對模型卡與權重授權。
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
