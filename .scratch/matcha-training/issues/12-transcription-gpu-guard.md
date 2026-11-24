<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 自動逐字稿與舞台共用 GPU 的保護
Status: ready-for-agent

依[規格](../spec.md)第 9 點。工單 05 的自動逐字稿在有 CUDA 時預設把 faster-whisper 載入到 GPU（`src/tts/training/transcription.py`），而且是在主程式行程內；舞台正在運作時，這會與 MuseTalk 與 LLM 搶用同一張 GPU，顯存吃緊時可能讓舞台出現 OOM。

- 開始自動逐字稿前，套用與訓練工作相同的檢查（工單 06 的舞台連線與剩餘顯存判斷，共用同一個函式，不要複製一份）：有舞台連線或剩餘顯存低於門檻時，**改用 CPU（int8）執行並在回應與介面上明確說明**，不要靜默切換，也不要直接拒絕。
- 查不到顯存時一律當成不足，改用 CPU。
- 回應要包含實際使用的裝置，介面顯示預估時間（CPU 較慢）。
- 測試以假的顯存探測與假的轉錄器進行，0 失敗、0 跳過。

介面約定（工單 08 依此實作）：`GET /api/tts/corpora/{slug}/transcription` 與啟動回應新增 `device`（`cuda` 或 `cpu`）與 `fallback_reason`（字串或 null，例如「有舞台連線」「剩餘顯存不足」「無法查詢顯存」）。工單 06 已合併，直接呼叫 `src/tts/training/gpu_guard.py`。

## Comments

### 2026-11-24 實作摘要（分支 `mv2/12-transcription-guard`）

沒有改 `web/`、`tools/tts-bench/`，也沒有動工單 13 的 `text-preview` 路由與 `start` 驗證；沒有啟動伺服器、沒有載入模型、不碰 GPU（測試用假連線數、假顯存探測、假轉錄器）。

**共用函式**：`src/tts/training/gpu_guard.py` 新增 `choose_transcription_device(stage_connections, read_vram, threshold_gb, cuda_available) -> DeviceChoice(device, fallback_reason)`，內部直接呼叫工單 06 的 `stage_connection_check` 與 `free_vram_check`，沒有複製判斷。自動逐字稿在 `TranscriptionJobs.start` 開始時決定一次（在 `asyncio.to_thread` 的工作執行緒內，因為會跑 `nvidia-smi`），結果傳給轉錄器工廠 `factory(model, device)`；工作進行中不再重問，也不遷移。門檻讀 `matcha.training_min_free_vram_gb`（與訓練開始同一個設定），由 `routes/tts_corpus.py` 的 `live_device_choice` 接上。

| 條件 | device | fallback_reason |
|---|---|---|
| 有舞台連線（不再讀顯存） | cpu（int8） | 有舞台連線 |
| 剩餘顯存低於門檻 | cpu | 剩餘顯存不足 |
| 讀不到顯存（探測失敗、無 nvidia-smi 等） | cpu | 無法查詢顯存 |
| 以上皆無，但沒有可用的 CUDA 裝置 | cpu | 沒有可用的 CUDA 裝置 |
| 以上皆無 | cuda | null |
| 工作中 GPU 實際跑不動、轉接器退到 CPU 重試 | cpu | GPU 執行失敗，已改用 CPU |

同時有舞台連線與顯存不足時，只回舞台連線這一個原因。剩餘顯存剛好等於門檻視為足夠。繁忙的 GPU 一律是改用 CPU，不會拒絕開始。

**介面（給工單 08）**：`POST /api/tts/corpora/{slug}/transcription`（202）與 `GET .../transcription` 的資料多兩個欄位 `device`（`"cuda"|"cpu"`）與 `fallback_reason`（字串或 null）。`state` 為 `idle`（含別的語料的工作）時兩者都是 `null`。其餘欄位不變。預估時間由介面自行依 `device` 計算（工單 06 的實測：CPU `small` 每句約 1 秒）；`fallback_reason` 為給管理者看的簡短中文句子。

**其他變動**：`TranscriptionJobs(store, factory, choose_device)` 的 `choose_device` 為必填（不提供預設，避免漏接保護）；`factory` 簽章改為 `(model, device)`；`transcription._cuda_available` 改為公開的 `cuda_available`；既有測試對應更新。

**驗證**：基準（`matcha-training` 當時的 tip，本分支切出時）2 failed（PDF OCR 與 role coordinator，既有）、2179 passed、3 skipped；本分支 2 failed（同兩項）、2198 passed、3 skipped，新增 19 個測試（`test_training_gpu_guard.py` 8、`test_training_transcription.py` 7、`test_tts_corpus_routes.py` 4）0 失敗 0 跳過。lock check、ruff、pyright（0 錯誤）、`check-integration.py` 通過；未動 `web/`，略過網頁步驟。合併最新 `matcha-training`（含工單 13）後，ruff、pyright 與所有 `tests/test_training_*.py`、`test_tts_corpus_routes.py`（615 個）通過；合併後未重跑整個測試套件。

**未解決**：真實 `nvidia-smi` 與真的 faster-whisper 在 GPU／CPU 上的行為未在此驗證（留給工單 10 實機驗收：舞台連線時開始轉錄應顯示 CPU 與原因；無舞台且顯存足夠時顯示 cuda）。
