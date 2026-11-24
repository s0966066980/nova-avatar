<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 自動逐字稿與舞台共用 GPU 的保護
Status: ready-for-agent

依[規格](../spec.md)第 9 點。工單 05 的自動逐字稿在有 CUDA 時預設把 faster-whisper 載入到 GPU（`src/tts/training/transcription.py`），而且是在主程式行程內；舞台正在運作時，這會與 MuseTalk 與 LLM 搶用同一張 GPU，顯存吃緊時可能讓舞台出現 OOM。

- 開始自動逐字稿前，套用與訓練工作相同的檢查（工單 06 的舞台連線與剩餘顯存判斷，共用同一個函式，不要複製一份）：有舞台連線或剩餘顯存低於門檻時，**改用 CPU（int8）執行並在回應與介面上明確說明**，不要靜默切換，也不要直接拒絕。
- 查不到顯存時一律當成不足，改用 CPU。
- 回應要包含實際使用的裝置，介面顯示預估時間（CPU 較慢）。
- 測試以假的顯存探測與假的轉錄器進行，0 失敗、0 跳過。

介面約定（工單 08 依此實作）：`GET /api/tts/corpora/{slug}/transcription` 與啟動回應新增 `device`（`cuda` 或 `cpu`）與 `fallback_reason`（字串或 null，例如「有舞台連線」「剩餘顯存不足」「無法查詢顯存」）。工單 06 已合併，直接呼叫 `src/tts/training/gpu_guard.py`。
