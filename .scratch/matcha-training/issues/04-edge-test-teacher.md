<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# Edge 測試用老師
Status: ready-for-agent
Blocked by: 03

依[規格](../spec.md)第 2、4 點與 ADR 0026。

- 從 jetson-orin 的 `distill_edge_teacher.py` 帶入並調整：以 `src.tts.edge_connection.EdgeConnectionPool` 逐句合成，失敗退避重試、句間等待。
- 內建句庫（問候、天氣、交通、口語、中英混合，約 900 句）取代對 `lexicon-zh.txt` 的依賴；可選「快速測試」約 15 分鐘或「標準」約 1 小時，也接受管理者上傳的文字檔。
- 聲線可選 Edge 的 zh-TW 聲音，預設 HsiaoChen；英文句由同一聲音念。
- 合成後做品質檢查（長度、音量、faster-whisper 比對），並寫成 03 的語料，來源為測試用老師。
- 啟動前必須取得「已閱讀並確認 MSA 條文」的紀錄；沒有確認紀錄時拒絕開始。
- 測試以假的 Edge 連線進行，不連網。

## 範圍補充（2026-11-24）

- 內建句庫視為已預先確認，所以測試必須保證：句庫中任何含阿拉伯數字的句子，經 03 的標準化器展開後都沒有未解決項。

- 只做服務層：提供可由背景工作呼叫的合成函式與進度回呼（逐句進度、可取消），**不新增路由**；路由與工作排程由 05、06 負責。
- 使用 `src/tts/training/` 的語料 API（工單 03 Comments），不要另建儲存格式。
- 「已確認 MSA 條文」的紀錄放在語料資料夾的來源宣告旁，由服務層檢查。

## Comments

### 2026-11-24 實作摘要（分支 `mv2/04-edge-teacher`）

只做服務層：沒有路由、GPU、網路或模型載入，測試以假的 Edge 連線進行。位置放在 `src/tts/training/`，沿用工單 03 的 `CorpusStore`，不另建儲存格式。新測試 96 個加 `test_training_corpus.py` 內 7 個，無跳過，已登記在 `tests/conftest.py` 的 `speech` 區。

**公開介面（給 05、06）**

- `sentences`：`library()`（901 句，每句帶 `category`）、`category_labels()`、`PRESETS`（`quick-test`「快速測試」目標 900 秒、`standard`「標準」目標 3600 秒）、`select_preset(key)`、`select_by_duration(seconds)`、`estimate_seconds(text)`、`parse_text_list(raw)`（管理者上傳的文字檔：UTF-8、一行一句、去空行與重複，每句最多 500 字、最多 5000 句、檔案最多 1 MB，錯誤訊息指出行號）。
- `edge_acknowledgement`：`MSA_CLAUSE`（`reference`、`effective`、`text`，介面要顯示的就是這段原文）、`record_acknowledgement(store, slug, shown_text, now=None)`、`read_acknowledgement`、`require_acknowledgement`（缺少或對應舊條文時丟 403 的 `CorpusError`）。
- `edge_teacher`：`run_synthesis(...)`（給背景執行緒，內部 `asyncio.run`）與 `synthesize_corpus(...)`（協程），參數 `store, slug, sentences, voice=DEFAULT_VOICE, pool=None, cancel=threading.Event, on_progress=callable, delay_seconds, max_attempts, base_backoff`（另有可注入的 `decode`、`sleep` 供測試）。回傳 `SynthesisReport(total, stored, needs_review, rejected, failed, skipped, cancelled, aborted, outcomes)`；進度回呼收到 `Progress(index, total, text, status, reason, line_id)`。`EDGE_ZH_TW_VOICES`（HsiaoChen、HsiaoYu、YunJhe，測試對齊 `runtime_settings`）、`DEFAULT_VOICE`。
- `audio_quality`：`assess_audio(samples)`、`to_wav_bytes`；長度 0.5 至 15 秒，RMS 至少 0.005，削波比例上限 0.1%，頭尾靜音修剪，正規化到 RMS 0.11 且峰值不超過 0.75。
- `transcript_check`：給 06 呼叫的 Whisper 比對掛鉤 `verify_with_asr(store, slug, transcribe, min_similarity=0.65, cancel=None, on_progress=None)`。`transcribe(path) -> str` 由 06 包 faster-whisper（模型載入與釋放都在 06）；相似度低於門檻的已確認句子改為 `excluded` 並列在報告裡。本層不載入任何模型。

**份量**：快速測試 220 句（估計 901 秒）、標準 833 句（估計 3600 秒）；整個句庫 901 句、估計 3939 秒。句庫六類加日常生活（問候、天氣、交通、口語、中英混合、數字日期電話、日常生活），資料在 `sentence_data.py`，全部自行撰寫、不依賴 `lexicon-zh.txt`；每句都能被 `normalize_digits` 完全展開，測試守住。估計用平均語速（中文 5.0 字／秒、英文 2.8 字／秒、每個標點 0.2 秒），實際長度合成後才知道。各類輪流取句，所以快速測試涵蓋全部類別，且是標準的子集合。

**重試與等待常數**（`edge_teacher`）：`MAX_ATTEMPTS = 5`、`BASE_BACKOFF_SECONDS = 4.0`（每次加倍，上限 `MAX_BACKOFF_SECONDS = 60.0`，`Retry-After` 較長時以它為準）、`SENTENCE_DELAY_SECONDS = 0.35`（句間，最後一句不等）、`MAX_CONSECUTIVE_FAILURES = 3`（連續三句用盡重試就中止，`aborted=True`）、等待以 `PAUSE_SLICE_SECONDS = 0.25` 分段，取消最慢 0.25 秒內生效。

**確認紀錄放哪裡**：語料資料夾內、`corpus.json`（來源宣告）旁的 `msa-acknowledgement.json`，欄位有時間戳記、條文出處、生效日與當時顯示的完整條文原文。為此 `CorpusStore` 新增 `read_sidecar` 與 `write_sidecar`，檔名限 `SIDECAR_FILES`（伺服器管理，不收使用者路徑）。只有 `record_acknowledgement` 會寫它，且 `shown_text` 必須與 `MSA_CLAUSE.text` 逐字相同，路由應在管理者勾選確認後才呼叫；合成函式與其他程式碼絕不自動建立。條文改字後舊紀錄不再放行。只有來源為 `edge-test-teacher` 的語料可以記錄與通過閘門。

**行為重點**

- 數字：先用工單 03 的 `normalize_digits`；可展開的，Edge 念展開後的中文字，句子也以展開後文字存成已確認。有無法判定的（例如 `$50`）就不猜：照原文合成、以原文存成**待確認**（`needs_review`，原因碼是 `unresolved` 的 `reason`），讓校對表標出來，`trainability()` 因此不通過，直到管理者修改文字。
- 品質檢查沒過的音檔不入庫，回報 `rejected` 與原因（`too_short`、`too_long`、`too_quiet`、`silent`、`clipped`、`decode_failed`）。通過且數字都展開的句子直接存成已確認，因為逐字稿就是念出的文字；之後 06 用 `verify_with_asr` 排除聽起來不符的句子。
- 語料已有相同文字的句子會略過（`skipped`），所以取消或中止後可以重跑續做。管理者的進度回呼拋例外不會中止合成。解碼、品質檢查與寫檔都在 `asyncio.to_thread` 內（CODING_STANDARDS 3），沒有傳入 `pool` 時自己開啟並在結束時關閉。
- 標示不變：Edge 語料仍是 Development only，確認紀錄不降級任何標示。

**驗證**：基準（`matcha-training` tip）2 failed、1759 passed、3 skipped（PDF OCR 與 role coordinator，與先前相同）；本分支 2 failed（同兩項）、1862 passed、3 skipped。lock check、ruff、pyright（含 `src/tts/training` 單獨執行）、`check-integration.py` 通過；未動 `web/`，略過網頁步驟。

**未解決**：`MSA_CLAUSE.text` 取自 `THIRD_PARTY_NOTICES.md` 的引文（英文原文）；若管理者要確認的條文與此不同，改這一處即可，舊的確認紀錄會自動失效。
