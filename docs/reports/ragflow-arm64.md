<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# RAGFlow ARM64 建置與部署驗證

驗證日期：2026-10-07；主機：Jetson AGX Orin，`aarch64`。

原主服務使用 `infiniflow/ragflow:v0.27.2` 的 AMD64 映像，啟動時發生
`exec format error`。本次以相同版本原始碼建立 ARM64 映像，已啟動並通過
真實文件解析、OCR、檢索與 Nova 客戶端驗證。

## 固定版本與元件

| 元件 | 版本／設定 |
| --- | --- |
| RAGFlow | v0.27.2；commit `a024bea0cd93f39e6652a42bf84dd20c55bc560b` |
| 原生映像 | `nova-avatar/ragflow:v0.27.2-arm64`，`linux/arm64` |
| 映像 ID | `sha256:2e597c620f697f3c759cea45c386e58292c1683701b7dae84c66129688e41c81` |
| API／任務執行器 | Python；`API_PROXY_SCHEME=python` |
| NumPy | 1.26.4，從來源編譯，沿用上游鎖定版本 |
| ONNX Runtime | 1.23.2，ARM64 CPU 版 |
| XGBoost | 1.6.0，ARM64 |
| Chromium／ChromeDriver | 154.0.8037.92，配對的 ARM64 套件 |
| SQL Server ODBC | Microsoft ODBC Driver 18，18.7.1.1-1 ARM64 |
| 嵌入程序 | 官方 Ollama v0.35.1 ARM64，含 JetPack CUDA runner |
| 嵌入模型 | BGE-M3，1024 維；已驗證 GPU 載入 |

Python、Node 建置基底映像固定 digest；DeepDoc 與文字拼接模型固定 Hugging Face
revision，下載資源產生 SHA-256 manifest。建置包含 Tika、NLTK、原生瀏覽器與正式
RAGFlow 網頁；mini-racer JavaScript 實際執行也通過。RAGFlow 本身沒有改成 TensorRT。

## 實際驗證

| 項目 | 結果 |
| --- | --- |
| 五個 Compose 容器 | 全部 healthy；主服務重啟次數 0 |
| RAGFlow 網頁 | `http://127.0.0.1:8088/`，HTTP 200 |
| 原生瀏覽器 | Chromium / ChromeDriver 無頭瀏覽器啟動、載入頁面與讀取標題通過 |
| API 與相依服務 | `system/healthz`：MySQL、文件引擎、Redis、物件儲存均 ok |
| 中文文字文件 | 解析完成，產生 1 個 chunk；Nova 命中預期檢修代碼 |
| 僅有影像的 PDF | DeepDoc OCR 解析完成，產生 1 個 chunk；Nova 命中預期校正資料 |
| 本次兩份文件解析 | 約 16.0 秒 |
| 本次 Nova 檢索 | 中文約 0.50 秒，英文 PDF 問題約 6.11 秒；均在 8 秒上限內 |
| 嵌入服務重啟後 | 啟動預熱完成；RAGFlow 嵌入連線驗證約 1.21 秒，成功 |
| 測試資料清理 | 僅刪除本次建立的臨時知識庫，驗證前後知識庫數量均為 0 |

時間為本次測量，不代表所有文件、問題長度與 GPU 併發負載均有相同速度。
第一次直接載入 BGE-M3 曾耗時約 40 秒，因此啟動時先預熱、預設保留模型。
預熱使用與 RAGFlow 相同的 `use_mmap=true` 選項，避免首次正式檢索重新載入 runner。

## 資料與啟動

現有資料卷、資料庫密碼與私有部署設定沿用，遷移前已備份至
`.local/ragflow/backups/arm64-migration/`。本機 MySQL 原先尚無 RAGFlow 資料表，
本次依 v0.27.2 正常初始化；沒有從 PC 自動搬入知識庫。
舊 Nova API 金鑰在本機無效，已備份並改為新服務建立的金鑰，保存在
`config/ragflow.env`（0600）。既有管理密碼未重設。

原數位人的 RAG 選項保留，但舊知識庫 ID 沒有本機資料。匯入自己的文件後，
需於 Nova 控制台重新選擇知識庫。初始管理帳號為 `admin@ragflow.io`，密碼在
`.local/ragflow/upstream/docker/.env` 的 `ADMIN_DEFAULT_PASSWORD`；密碼不寫入報告。

一般 `bash scripts/start-jetson.sh` 會自動帶起已準備的 RAGFlow。
`NOVA_START_RAGFLOW=0` 可略過；兩種朗讀專用模式仍略過。
重建、部署與連線指令見 [部署文件](../ragflow.md)。

## 專案檢查

- RAGFlow focused tests：16 通過。
- 品牌、授權與整合稽核：通過。
- 完整 Python 測試：533 通過，4 跳過，1 項影像合成效能測試失敗。
  該測試在 Orin 既有的 30 ms 門檻未通過；獨立重跑約 34.8 ms。本次未修改影像合成程式。
- Web 測試：93 通過；Web build：通過。
- Compose 版本、映像、連接埠、資源上限與 shell 語法檢查：通過。

詳細測試紀錄與結果 JSON 位於 `.scratch/ragflow-arm64/`，不包含連線金鑰。

來源：[固定版本 ARM64 建置說明](https://github.com/infiniflow/ragflow/blob/v0.27.2/docs/develop/build_docker_image.mdx)、
[官方 Ollama 發布](https://github.com/ollama/ollama/releases/tag/v0.35.1)。
