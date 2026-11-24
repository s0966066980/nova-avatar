<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 上傳錄音與逐字稿
Status: resolved
Blocked by: 03

依[規格](../spec.md)第 5、6、7 點。

- 上傳音檔與來源宣告：選「自己錄的」或「有書面授權」要有聲明，選「開發用」只能產出 Development only。檢查大小、格式；轉成 16 kHz 單聲道並做 `audio_qc` 檢查。
- 逐字稿：上傳同檔名的 `.txt` 或 `metadata.csv`（`檔名|文字`）；沒有逐字稿時用 faster-whisper 產生並轉成繁體中文，使用已快取的模型，在工作中載入、完成後釋放。
- 校對 API：逐句修改、排除、確認；數字展開後的文字一併回傳；全部確認前不得標示為可訓練。
- 新路由全部登記 `ROUTE_ACCESS` 為 ADMIN（ADR 0021）。

## 範圍補充（2026-11-24）

- 新路由集中放在新檔 `src/server/routes/tts_corpus.py`，只在 `routes/__init__.py`、`server.py`、`access.py` 加註冊與權限列，避免與 06（`routes/tts_training.py`）衝突。
- 使用 `src/tts/training/` 的語料 API（工單 03 Comments），不要另建儲存格式；音檔解碼與品質檢查在這張工單做。
- 自動逐字稿以背景執行緒進行，請求不得阻塞事件迴圈（CODING_STANDARDS）。

## Comments

### 2026-11-24 實作摘要（分支 `mv2/05-upload-transcripts`）

沒有改 `web/`、沒有啟動伺服器、沒有載入真模型（測試用假轉錄器與假 `WhisperModel`）。新測試約 155 個（`tests/test_training_{audio_decode,transcripts,ingest,transcription}.py`、`tests/test_tts_corpus_routes.py`，另在 `test_training_corpus.py` 加 3 個），無跳過。

**新模組（`src/tts/training/`）**：`audio_decode.py`（上傳檔解碼成 16 kHz 單聲道，並把品質檢查結果寫成繁體中文訊息）、`ingest.py`（來源宣告與上傳）、`transcripts.py`（`.txt` 與 `metadata.csv`）、`transcription.py`（背景轉錄工作與 faster-whisper 轉接）。品質檢查本身（頭尾靜音修剪、0.5–15 秒、RMS ≥ 0.005、校正到約 0.11 RMS 且峰值上限 0.75、削波）與相似度比對不重寫，直接用工單 04 合併進來的 `audio_quality.assess_audio` 與 `transcript_check.similarity_ratio`（規則同 jetson 的 `audio_qc.py`）。06 若要對上傳語料做 Whisper 比對，可把 `FasterWhisperTranscriber.transcribe` 交給 `transcript_check.verify_with_asr`。路由在 `src/server/routes/tts_corpus.py`，只在 `routes/__init__.py`、`server.py`、`access.py` 加註冊與權限列。對 03 的 `CorpusStore` 只加兩個小介面：`confirm_pending(slug, line_ids=None)`（一次寫入的批次確認）與 `set_text(..., only_if_empty=True)`；`_clean_text` 改名為公開的 `clean_text`。

**路由（全部 ADMIN，已在 `ROUTE_ACCESS`；回應格式 `{"code":0,"msg":"ok","data":...}`，錯誤 `{"code":-1,"msg":"繁體中文原因"}`，轉錄匯入錯誤另有 `"problems":[句子...]`）**

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/api/tts/corpora` | `{"corpora":[summary...]}` |
| POST | `/api/tts/corpora` | JSON `{"slug","source","consent"}`；建立並宣告來源 |
| GET | `/api/tts/corpora/{slug}` | summary 加 `"lines":[line...]`（校對表） |
| POST | `/api/tts/corpora/{slug}/lines` | multipart：`audio`（檔案，必要）、`text`（選填）；一次一個檔，回 `{"line","duration"}` |
| PUT | `/api/tts/corpora/{slug}/lines/{line_id}` | JSON `{"text"?,"review"?}`（至少一項）；回 `{"line","summary"}` |
| GET | `/api/tts/corpora/{slug}/lines/{line_id}/audio` | 該句音檔（`audio/wav`，`no-store`） |
| POST | `/api/tts/corpora/{slug}/transcripts` | multipart：多個欄位 `files`（`.txt` 或一個 `metadata.csv`）；回 `{"applied","without_transcript":[id...]}` |
| POST | `/api/tts/corpora/{slug}/confirm` | JSON `{"line_ids"?}`（可省略）；批次確認有逐字稿的待確認句，回 `{"confirmed","without_text","summary"}` |
| POST | `/api/tts/corpora/{slug}/transcription` | JSON `{"line_ids"?,"model"?}`，202，回 status |
| GET | `/api/tts/corpora/{slug}/transcription` | status；別的語料的工作顯示 `idle` |
| DELETE | `/api/tts/corpora/{slug}/transcription` | 取消（目前這一句做完才停），回 status |

**資料形狀（給 08）**

- summary：`{slug, source, declared_at, usage_label, counts:{pending,confirmed,excluded,total}, trainable, reasons:[source_missing|pending_lines|no_confirmed_lines|unresolved_digits]}`。
- line：`{id, original_name, text, normalized_text, unresolved:[{text,start,end,reason}], review:"pending|confirmed|excluded", audio_url}`；`unresolved` 的位置指向 `text`（原文）。
- 轉錄 status：`{state:"idle|running|done|cancelled|failed", slug, model, total, done, skipped, failed:[{line_id,message}], message, cancel_requested}`。`skipped` 是工作進行中管理者自己填了文字的句子（不覆寫）。

**行為與限制**

- 來源宣告：`self-recorded`、`written-authorization` 要 `consent: true`（嚴格為 `true`），`development-unlicensed` 不用（標示 Development only）；`edge-test-teacher` 不能經這組路由宣告，也不接受上傳到 Edge 語料（409）；未宣告來源的語料不接受上傳（409）。建立語料時 slug 以 `fullmatch` 驗證（沿用 `VOICE_MODEL_ID`），路徑一律由伺服器產生。
- 上傳上限 20 MB（`ingest.MAX_UPLOAD_BYTES`，413）；副檔名限 wav、mp3、flac、ogg、m4a、webm（415）；依魔術位元組選 demuxer 並真的解碼（不是音檔 415，解不開 422）；原始錄音最多解碼 60 秒，修剪後須在 0.5–15 秒，否則 422。一律存成 16 kHz 單聲道 PCM16 `.wav`，`original_name` 只當顯示。解碼與品質檢查在 `asyncio.to_thread` 執行。
- Whisper 相似度檢查（門檻 0.65）只在服務層（`ingest_audio(..., text=, recognizer=)`），路由沒有開這個選項，因為每次上傳載一次模型太重。
- 逐字稿匯入：`.txt` 檔名（去副檔名）對應音檔的原始檔名；`metadata.csv` 為 `filename|text`，可帶表頭 `filename|text`，檔名可含或不含副檔名；文字含 `|` 視為錯誤。`.txt` 上限 8 KB、csv 上限 2 MB、最多 5001 個檔。解析與比對全有或全無：所有問題（行號、找不到對應音檔、多個同名音檔、重複）一次列出，什麼都不套用。已確認的句子被套用新文字會退回待確認。
- 自動轉錄：只處理沒有逐字稿且未排除的句子；模型限 `small`、`medium`（預設）、`large-v3`，僅用本機快取（`local_files_only=True`，不下載；沒有快取則工作失敗並說明）；語言自動偵測，輸出以 OpenCC `s2twp` 轉繁體；優先用 GPU，GPU 失敗（例如 CUDA 函式庫不在路徑）自動退到 CPU 重試一次；同一時間只有一個工作（409）；在自己的背景執行緒載入模型，結束、取消或失敗都會 `close()` 釋放；伺服器關閉時取消並等待。結果寫成待確認，用 `only_if_empty` 避免覆寫管理者同時輸入的文字。
- 校對：`PUT` 改文字會退回待確認；沒有逐字稿的句子不能確認；整份語料全部確認（無待確認、無未解數字）前 `trainable` 為 false。
- 不提供刪除語料與刪除單句（要先查訓練工作並移入 `.deleted`，留給 06）。校對表不回傳每句長度（manifest 沒存）；需要時由 08 另議。

**驗證**：基準（`matcha-training` tip）2 failed、1759 passed、3 skipped；本分支 2 failed（同兩項：PDF OCR 與 role coordinator）、1916 passed、3 skipped。合併 `matcha-training`（含工單 04）後：2 failed（同兩項）、2010 passed、3 skipped。lock check、ruff、pyright（0 錯誤）、`check-integration.py` 通過；未動 `web/`，略過網頁步驟。
