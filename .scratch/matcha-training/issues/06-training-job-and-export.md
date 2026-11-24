<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 訓練工作與寫入聲線模型清單
Status: resolved
Blocked by: 02, 03, 04

依[規格](../spec.md)第 8、9 點與「信任邊界與資料位置」。

- 從 jetson-orin 帶入並調整 `tts_training_jobs.py`、`routes/tts_training.py`、`train_matcha.py`、`matcha_arch.py`、`export_matcha_onnx.py`：以 `.local/matcha-train/` 的 Python 啟動獨立子程序，同一時間只進行一件，可取消並釋放 GPU，日誌可讀取。
- 拒絕條件：有舞台連線，或剩餘顯存低於門檻（初始 8 GB，可設定）；回應要說明原因，供介面顯示。
- 只有狀態為「全部已確認」的語料才能訓練；訓練前再檢查一次。
- 寫入聲線模型清單：寫入 `models/tts/<slug>/` 與 `voice.json`（使用限制標示依 03 計算）。第一版**不提供任何下載路由**，所有聲線模型只留在這台機器。
- 新路由全部登記 `ROUTE_ACCESS` 為 ADMIN；測試用假子程序，不載入真實模型，0 失敗、0 跳過。

## 從工單 02 帶來的注意事項

- 訓練環境用 `scripts/setup-matcha-train.sh` 建立（上游 `matcha-tts==0.0.7.2`、MIT；底模已驗證可嚴格載入，`.local/matcha-train/`、`.local/matcha-base/` 已在 `.gitignore`），請直接沿用，不要另寫安裝流程。
- 上游 `MatchaTTS.forward` 回傳 4 個值，jetson 的 `train_matcha.py` 只解 3 個，移植時要修正。
- 一批裡最短的語句少於 `out_size` 時會出形狀錯誤；訓練要把 `out_size` 縮到該批最短長度，或過濾過短語句。
- cu124 變體只做過解析，沒有在 GPU 上實測；第一次在 GPU 上跑要記錄顯存與耗時，用來校準 8 GB 阻擋門檻。

## 範圍補充（2026-11-24）

- 工作步驟為：合成（僅限測試用老師語料，呼叫工單 04 的服務層）→ 品質檢查 → 訓練 → 寫入聲線模型清單；上傳錄音的語料略過合成步驟。
- 工作路由集中在 `routes/tts_training.py`；語料與上傳路由屬於 05（`routes/tts_corpus.py`）。

## Comments

### 2026-11-24 實作摘要（分支 `mv2/06-training-job`）

沒有改 `web/`、沒有啟動伺服器、單元測試不載入模型也不碰 GPU（假子程序、假 Edge、假 Whisper、假顯存探測）。另在自己的工作樹用 CPU 跑了真的子程序冒煙（見下）。新測試 約 170 個（`tests/test_training_{jobs,routes,bundle,asr,processes,preparation,manifest,gpu_probe}.py`、`tests/test_matcha_training_scripts.py`，假程序在 `tests/training_fakes.py`），無跳過。

**路由（全部 ADMIN，已在 `ROUTE_ACCESS`；回應 `{"code":0,"msg":"ok","data":...}`，錯誤 `{"code":-1,"msg":"繁體中文原因"}`）**

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/api/tts/training?corpus=<slug>&name=<名稱>` | `data = {job, preflight, settings}`。`job` 是進行中或最近一件的狀態（沒有則 `null`）；`preflight = {can_start, checks:[{id,label,status,reason,detail}]}`（`corpus`、`name` 省略時 `corpus` 檢查為不通過）；`settings = {min_free_vram_gb, whisper_model}` |
| POST | `/api/tts/training/start` | JSON `{corpus, name, voice?, preset?, sentences?}`。`voice` 只能是 `edge_teacher.EDGE_ZH_TW_VOICES`；Edge 語料必須給 `preset`（`quick-test`／`standard`）或 `sentences`（一行一句的文字，最多 1 MB），上傳語料忽略這三個欄位。成功回 `data = job`；檢查不過回 409 並帶 `preflight`（同上結構）；欄位格式錯 400 |
| POST | `/api/tts/training/cancel` | 無內容。有進行中的工作回 `data = job`（`status:"cancelling"`），沒有則 `data:null`、HTTP 200 |
| GET | `/api/tts/training/log?offset=<n>` | `data = {job_id, start, lines, next, total}`；`offset` 是絕對行號，下一次用回應的 `next`。記憶體只留最近 2000 行，`start` 大於 `offset` 代表更早的行已被丟掉（完整日誌在檔案裡）。重新啟動後讀最近一件工作的日誌檔 |

沒有任何下載或匯出路由（測試守住：訓練路徑底下只有上面四條，路由表沒有 `export`／`download`）。聲線模型 ID 由伺服器產生（`trained-<UTC 日期時間>-<4 碼十六進位>`），請求不能指定。

**job 的形狀（給 08）**：`{id, corpus, name, voice_id, usage, source, status, stage, stages:[{id,label,status,detail,progress,seconds}], progress(0-100), message, error, started_at, finished_at, metrics, log_lines}`。`status` 為 `running|cancelling|done|failed|cancelled`；階段 `id` 依序是 `environment`（準備訓練環境）、`synthesis`（合成語料，僅 Edge）或 `preparation`（整理語料，僅上傳）、`quality`（品質檢查，含 Whisper 比對）、`training`（訓練）、`export`（寫入聲線模型清單）；階段 `status` 為 `pending|running|done|failed|cancelled`，`progress` 0 到 1。整體進度的權重：環境 2、合成 20、整理 8、品質 15、訓練 55、寫入 5。`metrics` 有 `lines`（進訓練的句數）、`step`、`total_steps`、`training_seconds`、`min_free_vram_mib`（訓練期間每 15 秒量一次剩餘顯存的最低值）。

**拒絕條件（`preflight.checks[].id`，順序固定）**：`admin`（永遠通過，路由守衛已擋）、`stage_connections`（`state.avatar_streams` 的數量，含連線中的佔位；`detail.count`）、`free_vram`（`nvidia-smi --query-gpu=memory.free` 第一張卡；`detail.free_gb`、`threshold_gb`；讀不到一律不通過並說明原因）、`environment`（`.local/matcha-train/venv/bin/python`、底模權重與 `models/tts/matcha-icefall-zh-en/` 的 tokens／lexicon／vocoder；`detail.missing`）、`other_job`、`edge_acknowledgement`（只有 Edge 語料；紀錄須對應目前條文）、`corpus`（`trainability`，原因換成中文句子；Edge 語料尚無句子時改為「合成後會再檢查一次」）、`corpus_size`（有已確認句子時才出現；以文字估計長度，低於 15 分鐘為 `warn`，只提醒不阻擋）、`model_name`（必填、至多 40 字、與既有聲線模型名稱不重複，NFKC 與大小寫不分）。`status` 為 `pass|fail|warn`，`can_start` 為沒有任何 `fail`。

**設定（`config/config.yaml` 的 `matcha:` 區段，載入時驗證）**：`training_min_free_vram_gb: 8`（0 到 1024 的數字）、`training_whisper_model: small`（`tiny|base|small|medium|large-v3`）。取消寬限秒數（SIGTERM 之後 10 秒再 SIGKILL）與訓練超參數（批次 16、35 個 epoch、學習率 1e-4、編碼器學習率 0.2 倍）在 `TrainingSettings`／`TrainingParams`，不經請求。

**流程細節**

- 子程序都用 `.local/matcha-train/venv/bin/python`（注意：工單原文寫的是 `.local/matcha-train/bin/python`，`setup-matcha-train.sh` 實際建在 `venv/` 底下），以獨立 session 啟動，取消時整個行程群組收到 SIGTERM，逾時再 SIGKILL；環境去掉 `PYTHONPATH`、`VIRTUAL_ENV`，設 `PYTHONNOUSERSITE=1`，不阻擋 GPU（不設 `CUDA_VISIBLE_DEVICES`）。腳本不用 `python -I`，因為它們要匯入同資料夾的 `matcha_arch`。
- 訓練文字只來自 `Corpus.training_lines()`（已確認且數字已展開的句子）。分詞在主程式行程做（需要 OpenCC）：`normalize_matcha_text`（與引擎推理前相同的繁轉簡與英文詞處理）加上 `lexicon_utils.text_to_phoneme_ids`，後者現在遇到任何數字就丟 `ValueError`，不再靜默丟掉。訓練腳本只讀 manifest 的 token ID。詞典是底模詞典加技術詞（`build_merged_lexicon`），同一份隨聲線模型安裝。沒有音檔、沒有 token 或 token ID 超出底模嵌入表（2190）的句子會略過並記在日誌。
- 品質檢查階段：先重新確認語料可訓練（Edge 合成後可能留下待校對句），再對每個已確認句子跑工單 04 的 `assess_audio`（不合格者在語料裡改為 `excluded` 並寫進日誌），正規化後的音檔寫到工作資料夾 `prepared/`；接著 Whisper 比對：在應用程式自己的直譯器開子程序（`python -m src.tts.training.whisper_worker`，`CUDA_VISIBLE_DEVICES=`，int8，CPU），經 `verify_with_asr`（門檻 0.65）排除不符的句子。這一步不會被靜默略過：模型載不起來或子程序中途死掉就讓工作失敗並顯示原因。上傳語料的解碼改用工單 05 的 `audio_decode.decode_to_16k_mono`（依魔術位元組選 demuxer，不讓 FFmpeg 自己探測）。
- Edge 合成呼叫工單 04 的 `run_synthesis`（在工作執行緒內），先要 MSA 確認紀錄；Edge 連續被拒絕（`aborted`）時工作失敗、已合成的句子保留，重新開始同一份語料會續做。
- 匯出：`export_matcha_onnx.py`（沿用 jetson 版，改成不依賴 CosyVoice 的路徑，`onnx==1.17.0` 加進 `integrations/matcha-train/requirements.{in,txt}`）複製底模的 vocoder、tokens、FST 並寫入訓練用詞典，然後在主程式的直譯器以 CPU 用 sherpa-onnx 載入並念一句（`python -m src.tts.training.verify_bundle`），確認 16 kHz 有聲音才安裝。安裝是「複製到 `models/tts/.installing-<id>/`、寫 `voice.json`、改名」，目標已存在就拒絕，失敗不留半成品；`voice.json` 的標示是 `Corpus.usage_label()`（底模 Research / Non-commercial 與語料來源取最嚴格者），語言 `["zh-TW","en-US"]`。安裝後工作資料夾只留 `log.txt`（取消與失敗也一樣：語料保留、訓練進度不保留）。
- 狀態存在 `data/tts/training/.jobs/job-*.json`（保留最近 20 件），日誌在 `data/tts/training/<slug>/jobs/<工作 ID>/log.txt`。伺服器重新啟動後第一次查詢，仍是 `running`／`cancelling` 的工作改為 `failed`（「伺服器重新啟動，訓練工作已中斷」），並對記錄的行程群組送 SIGTERM（只在 `/proc/<pid>/cmdline` 含 `tts-distill` 時）。
- 訓練腳本（`tools/tts-distill/`，沿用 jetson 檔頭並加 Modified 註記）：`MatchaTTS.forward` 改解 4 個值；`out_size` 改為依批次中最短的句子縮到 4 的倍數（不足 32 幀則不裁切），而不是依補齊後的批次寬度；`weights_only=True`；`matcha_train_env_check.py` 改為匯入 `matcha_arch` 的建模與載入函式，不再有兩份。刪掉 jetson 版未用到（預設為 0）的 `--dur-bounds-weight`、`--encoder-anchor` 與 `--dry-run`。
- 給工單 12：舞台連線與剩餘顯存兩個檢查是 `src/tts/training/gpu_guard.py` 的 `stage_connection_check`、`free_vram_check`（加上 `count_stage_connections`、`gpu_probe.read_free_vram`），訓練前檢查與日後的自動逐字稿應呼叫同一組。

**CPU 真實冒煙（我自己的工作樹，`MATCHA_TRAIN_TORCH=cpu bash scripts/setup-matcha-train.sh`、`CUDA_VISIBLE_DEVICES=`；腳本在 scratchpad，不屬於測試）**

- 完整工作（6 句假音檔、含「我有3個蘋果」「2026年」、`max_steps=2`、Whisper 與 Edge 為假、其餘全真）：環境 → 整理 → 品質 → 真的訓練子程序 2 步（loss 6.7 → 5.7）→ 真的匯出 → 真的 sherpa-onnx 載入檢查 → 寫入 `models/tts/trained-…/`，約 8 到 13 秒，`list_voice_models` 列出該模型，標示 Research / Non-commercial、語言 zh-TW 與 en-US，目錄有 `voice.json`、`model.onnx`、詞典、tokens、vocoder 與三個 FST。
- 真的取消：訓練到第 20 步時取消，SIGTERM 後 0.1 秒內子程序消失（`pgrep` 為 0），狀態 `cancelled`，沒有模型寫入，工作資料夾只剩 `log.txt`，語料不動。
- 以底模權重直接匯出的 ONNX 能被 sherpa-onnx 載入並念出 1.8 秒的 16 kHz 語音。
- 真的 CPU Whisper 子程序（`SubprocessTranscriber`）：`tiny` 就緒 1.3 秒、每句約 0.3 秒；`small` 就緒 3.9 秒、每句約 1.1 秒（2 到 3 秒的句子），對 Matcha 底模念出的 3 句，相似度 `small` 為 1.00／0.90／0.86、`tiny` 為 1.00／0.60／0.92。換算：快速測試約 220 句約 4 到 5 分鐘、標準約 830 句約 15 到 17 分鐘（`small`，在忙碌的開發機上量的）。
- 只用假程序驗證、沒有真實跑過的：Edge 合成階段（假 `run_synthesis`）、Whisper 比對接進整個工作（假轉錄器）、`nvidia-smi` 探測的真實輸出格式（只在本機讀過一次，正常）、重啟後孤兒行程的清理（只驗證了 `/proc` 判斷）。

**工單 10 實機驗收還要在 GPU 上確認並記錄**

1. `MATCHA_TRAIN_TORCH=cu124` 的環境（`setup-matcha-train.sh` 預設）在 4090 上實際安裝並能訓練；第一次訓練的剩餘顯存最低值（工作的 `metrics.min_free_vram_mib`，也寫在日誌「[訓練] 剩餘顯存」）與訓練耗時（`metrics.training_seconds`），用來校準 8 GB 門檻與 40 到 60 分鐘的預估。批次 16 與 bf16 autocast 的顯存尚未實測。
2. 訓練期間舞台確實連不上（拒絕條件）、取消後 `nvidia-smi` 顯存回到訓練前。
3. Whisper 比對在場域主機（CPU）上的實際耗時，特別是標準份量。
4. 預設超參數（35 epoch）對 220 句與 833 句各多少步、loss 走勢；訓練出的聲線模型實際聽感與疊字（工單 11 的評量）。
5. Edge 連線的真實合成（限流、重試、續做）與完整「快速測試」一次。

**未解決與決定**

- Edge 的「上傳文字檔要校對」要求在合成前就有可校對的句子，但語料資料層一句必須有音檔；目前 `start` 直接收 `sentences`（一行一句），校對流程屬於 05／08 的設計，這裡沒有補。
- 分詞是對 sherpa-onnx 推理時詞典斷詞的近似（最長匹配、沒有插入空白符號與 BOS/EOS，與 jetson 版相同）；jetson 評比中的疊字問題是否與此有關，仍留給工單 11 的評量判斷。
- 預設用 `best.pt`（EMA 損失最低者，至少訓練 200 步或總步數一半之後才記錄），沒有另外做驗證集。
- 沒有刪除語料或聲線模型的路由（要先查訓練工作並移入 `.deleted`，仍留待後續）；訓練中排除的句子在語料裡是 `excluded`，管理者可在校對表重新確認。
- 完整 `matcha-tts` 以外多裝了 `onnx==1.17.0`（Apache-2.0）與 `protobuf`（BSD-3-Clause）；`THIRD_PARTY_NOTICES.md` 屬工單 09。

**驗證**：基準（`matcha-training` tip，含工單 05）2 failed（PDF OCR 與 role coordinator，既有）、2010 passed（取自工單 05 紀錄的合併後基準）、3 skipped；本分支 2 failed（同兩項）、2179 passed、3 skipped，新測試 0 失敗 0 跳過。lock check、ruff、pyright（0 錯誤）、`check-integration.py` 通過；未動 `web/`，略過網頁步驟。

### 2026-11-24 程式審查修正（分支 `mv2/review-fixes`，涵蓋工單 05、06、12、13、14）

沒有啟動伺服器、沒有載入模型、不碰 GPU；全部用假程序、假 Edge、假 Whisper、假探測驗證。Python 3.10 相容（`python3.10 -m py_compile` 通過；逾時仍用 `asyncio.TimeoutError`）。

**A. 訓練工作生命週期**（`tts_training_jobs.py`、`routes/tts_training.py`、`asr.py`、`transcription.py`）

- 伺服器關閉：`TrainingJobManager.shutdown()` 取消進行中的工作（SIGTERM、寬限期、SIGKILL），逾時（寬限期加 5 秒）仍未結束就直接 `kill()` 子程序；`routes/tts_training.py` 的 `register` 加 `on_shutdown`。測試：`test_shutdown_cancels_the_running_job_and_stops_its_child_so_the_gpu_is_freed`、`test_shutdown_escalates_to_sigkill_for_a_child_that_ignores_sigterm`、`test_shutdown_kills_the_child_directly_when_the_worker_cannot_finish_in_time`、`test_shutdown_with_nothing_running_does_nothing`、`test_shutdown_during_edge_synthesis_stops_it`、`test_shutdown_kills_a_stuck_whisper_child`、路由 `test_startup_recovers_interrupted_jobs_and_shutdown_stops_the_running_one`、`test_a_job_running_at_shutdown_is_cancelled_and_its_child_stopped`。
- 啟動時復原：`recover()` 改為公開，由 `on_startup` 在背景執行緒執行一次；`status`、`read_log`、`start` 不再延遲復原。孤兒清理 `stop_orphan_training` 改為 SIGTERM、等寬限期、SIGKILL、再有界等待群組消失；比對字串加入 Whisper 工作程式。測試：`test_recovery_runs_at_startup_not_on_the_first_request`、`test_an_interrupted_job_that_was_cancelling_is_also_recovered`、`test_an_orphan_that_exits_on_sigterm_is_not_killed`、`test_an_orphan_that_ignores_sigterm_is_killed_after_the_grace_period`、`test_the_orphan_cleanup_waits_for_the_group_to_be_gone_but_not_for_ever`、`test_a_whisper_worker_left_behind_is_stopped_too`、`test_a_reused_pid_of_an_unrelated_process_is_left_alone`；既有三個重啟測試改為先呼叫 `recover()`。
- 取消競態：`cancel()` 在 `job.lock` 內才判斷是否仍進行中，剛結束的工作不會被蓋成 `cancelling`，「已有工作進行中」也不會卡住。測試：`test_cancel_does_not_overwrite_a_job_that_finished_meanwhile`。
- Whisper 子程序：`SubprocessTranscriber` 加啟動逾時（300 秒）與每句逾時（120 秒，`TrainingSettings.whisper_utterance_timeout_seconds`）、監看取消事件並立即 `kill()`（`TranscriberCancelled`）；子程序經 `_tracked_spawn` 追蹤，pid 寫進工作狀態（`Job.process`，`pid` 為衍生屬性），訓練階段結束與逾時都會清除；`_quality` 把取消造成的錯誤轉成取消，其他轉成 `JobFailed`。測試（`test_training_asr.py`）：`test_an_utterance_that_gets_no_answer_times_out_and_the_child_is_killed`、`test_after_a_timeout_the_transcriber_does_not_use_the_dead_child_again`、`test_the_timeout_counts_per_utterance_not_for_the_whole_run`、`test_a_child_that_never_gets_ready_times_out`、`test_cancel_kills_the_child_without_waiting_for_the_utterance`、`test_a_cancel_before_the_first_utterance_sends_nothing`；（`test_training_jobs.py`）`test_the_whisper_child_pid_is_saved_in_the_job_state_and_cleared_afterwards`、`test_cancel_kills_a_stuck_whisper_child_at_once`、`test_a_whisper_child_that_stops_answering_fails_the_job_with_the_reason`。
- 自動逐字稿進行中拒絕開始訓練：新增前置檢查 `transcription`（排在 `other_job` 之後，附原因），`TranscriptionJobs.running()`，`build_manager(app)` 在被詢問時才去找語料路由的 `TranscriptionJobs`（與註冊順序無關）；前端三份 locale 補 `checks.transcription`。測試：`test_an_automatic_transcription_in_progress_blocks_a_start_with_a_reason`、`test_without_a_transcription_the_check_passes_and_follows_the_other_job_check`、`test_running_is_true_only_while_a_job_works`、`test_the_live_manager_refuses_a_start_while_the_corpus_transcription_runs`、`test_the_live_manager_without_corpus_routes_has_no_transcription_to_wait_for`。
- `start()` 不再在 `self._lock` 內跑 nvidia-smi：慢檢查在鎖外，鎖內只重做便宜的互斥檢查（其他工作、逐字稿）並登記工作，兩個同時開始只會有一個成功。測試：`test_start_does_not_hold_the_manager_lock_while_the_gpu_is_probed`、`test_two_starts_at_the_same_time_run_one_job`。
- 附帶：`tests/conftest.py` 加自動套用的 fixture，把 `corpus.TRAINING_ROOT` 指到暫存目錄，避免測試啟動的伺服器在開機時復原（甚至終止）場域真實的訓練工作。

**B. 數字的縱深防禦**：`edge_teacher.synthesize_corpus` 在任何 Edge 請求之前拒絕含未展開數字的清單（409，列出每一句與片段）；`sentences.select_preset` 每次選取都檢查內建句庫，發現未展開數字就報錯。測試：`test_a_list_with_unresolved_digits_is_refused_before_any_edge_request`、`test_every_unresolved_fragment_is_listed_in_the_refusal`、`test_a_preset_whose_sentence_cannot_be_expanded_is_refused_at_runtime`、`test_the_real_presets_expand_every_digit`；原本預期「合成但待校對」的兩個測試改為新行為。

**C. 逐字稿比對**：`verify_with_asr` 同時比對數字展開後的文字與原文，取較高分（排除時回報展開後的文字）。測試：`test_a_proofread_digit_line_is_compared_with_the_digits_read_out`、`test_the_raw_text_still_counts_when_whisper_writes_digits`、`test_a_digit_line_that_really_differs_is_still_excluded_and_reports_the_spoken_text`（「2026年11月24日」對「二零二六年十一月二十四日」）。

**D. Edge 音檔**：`GET /api/tts/corpora/{slug}/lines/{id}/audio` 對 `edge-test-teacher` 語料回 403（繁體中文訊息），上傳語料不變；`VtDone.vue` 的試聽播放器加 `controlsList="nodownload"`，保留 `autoplay`。測試：`test_edge_teacher_audio_is_neither_played_back_nor_taken_out`、`test_an_unknown_corpus_or_line_is_still_404_for_the_audio_route`；網頁 `完成畫面：三個試聽按鈕…`（補斷言）。

**E. 條文確認**：`POST .../acknowledgement` 除了完全一致的 `shown_text`，還必須 `confirmed: true`（缺少、非布林 `true` 一律 400，什麼都不寫）。`api.recordAcknowledgement(slug, shownText, confirmed)` 只在明確傳入 `true` 時送 `true`；`store.confirmEdge` 在核取方塊通過檢查後送 `state.edge.checked`（`VtEdgeConfirm.vue` 本身經 store 送出，沒有另外改動）。測試：`test_the_exact_text_alone_is_not_a_confirmation`、`test_a_body_without_the_confirmed_flag_records_nothing`（既有確認測試改為送 `confirmed`）；網頁 `條文確認只有明確傳入 true 才送 confirmed: true，其他一律送 false`，並補 `建立語料與記錄 Edge 條文確認…`、`Edge 確認：條文來自伺服器…`的斷言。

**F. 事件迴圈**：`list_corpora`、`get_corpus`、`edit_line`、`confirm_lines`、`upload_line` 的 `_summary`／`_detail`／`_line_payload` 與 `import_transcripts` 的解析（`_parse_transcript_files`）都進 `asyncio.to_thread`。測試：`test_review_payloads_are_built_off_the_event_loop`、`test_transcript_files_are_parsed_off_the_event_loop`。`endpoint` 裝飾器補上型別標註（重構後 pyright 才不會推論失敗）。

**G. 小項**：`scripts/setup-matcha-train.sh` 的註解改為英文；診斷證據的四個 `.py` 補 Nova Avatar SPDX 檔頭；`_corpus_checks` 用 `REVIEW_CONFIRMED` 常數。

**未處理（已寫進規格的 Follow-ups）**：重複的 Whisper 模型清單與預設值、兩個 `Transcriber` 型別、重複的 8.0／`small` 預設、前後端重複的 `strictest`、重複的 `source == SOURCE_EDGE_TEST_TEACHER` 分支、分層匯入問題、`VtJob.vue` 的鍵比對與後端 `STAGE_LABELS` 繞過 i18n、`openCorpus` 重開草稿時遺失 Edge 聲音／份量／自訂清單。

**驗證**：基準（`matcha-training` tip，Python 3.11 的 CI venv）2 failed（PDF OCR 與 role coordinator，既有）、2308 passed、3 skipped；網頁（Node 22）357 pass、0 fail、0 skip。本分支 lock check、ruff、pyright（0 錯誤）、`check-integration.py` 通過；pytest 2 failed（同兩項）、2357 passed（新增 49）、3 skipped；網頁 lint 通過、358 pass（新增 1，其餘為修改既有測試）、0 fail、0 skip、`npm run build` 通過。新測試 0 失敗 0 跳過。

**工單 10 實機驗收補充**：真實 `nvidia-smi` 與真 faster-whisper 子程序的逾時／取消、真的關閉伺服器時 GPU 顯存是否回到訓練前、真的重啟後孤兒行程（含 Whisper）的 SIGTERM 到 SIGKILL 清理，都只用假程序驗證過。
