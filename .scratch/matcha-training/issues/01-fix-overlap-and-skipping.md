<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 修正跳音：Matcha 片段預取
Status: resolved

依[規格](../spec.md)第 1 點與「疊音與跳音診斷」。診斷結論：跳音最可能來自 Matcha 沒有預取，疊音則是模型權重本身的問題（改由 11 評量、重訓後驗證，main 沒有程式修法）。

- `src/tts/base.py` 在片段合成結束後才等待上一片播完，Matcha 沒有像 Edge 那樣預取（`edge.py` 約 :796），日誌量到片段之間 221–280 ms 的空白，Edge 則約 20 ms。
- 仿照 Edge 的做法，在播放目前片段時先合成下一片並暫存；沿用既有的輪次隔離、插話取消與音訊主時鐘規則（ADR 0007），取消或換輪時要丟棄暫存。
- 合成本身不是瓶頸（RTF 約 0.017），所以不要增加執行緒或改變模型參數。
- 測試用假的合成器驗證：片段間隔縮短、插話與換輪時不播出舊輪次的暫存、同一模型的鎖仍序列化合成。
- 驗收：離線測試通過；實機日誌中 Matcha 片段間隔降到接近 Edge（約 20–50 ms）；舞台再聽一次是否仍有跳音。若仍有，依診斷建議在 `put_audio_frame` 記錄每一幀的時間、`media_sequence` 與片段邊界，並同時錄 WebRTC 輸出，另開工單。

## Comments

### 2026-11-24 診斷摘要

- 離線以 main 的引擎路徑重現：12 句已知會疊音的句子各合成 3 次，Whisper turbo 轉寫後 17/36 有多餘疊字（例如「去去法國」「液液體體」），詞時間戳完全相同，是確定性重複；12 句乾淨句只有 1/32。
- 四組權重與詞典對照：曉臻權重＋曉臻詞典 17/36；曉臻權重＋base 詞典 13/24；base 權重＋曉臻詞典 1/24；base 權重＋base 詞典 1/24。換詞典沒用，換權重才消失，所以原因在曉臻的聲學權重，不在詞典前端，`noise_scale` 與 `length_scale` 也與 base 相同。
- jetson 原版的評比音檔：中文 400 句中 42 句（10.5%）有疊字，base 模型 500 句中 5 句（1%），所以不是移植造成。
- 已排除：sherpa callback 區塊重疊、`pcm_emitter` 截斷或重複（輸出與輸入逐樣本相同）、取樣率、併發（有鎖）、main 與 jetson 合成路徑的差異。
- 未能測試：WebRTC 端實際擷取，所以「聽到的跳音就是片段空白」仍是推論；MuseTalk 滿載下的 CPU 競爭也未量測。
- 證據：`../evidence/2026-11-24-diagnosis/`（轉寫與四組對照的 JSON 與腳本；音檔約 18 MB 只留在暫存目錄，不進 git）。

### 2026-11-24 實作：Matcha 片段預取（分支 `mv2/01-matcha-prefetch`，提交 f1db0f5）

- 位置：`src/tts/engines/matcha.py` 的 `MatchaTTS`（`process_tts` 覆寫）。一條合成執行緒從 `msgqueue` 取文字並合成，最多在播放中的片段之前暫存 1 片（`MAX_HELD_FRAGMENTS`）；發聲執行緒取出暫存片段逐 20 ms 幀送出。有暫存片段時不等上一片播完就接著送，由有界播放佇列的背壓控制節奏（與 Edge 相同）；沒有暫存時才等播放結束，`_synthesis_active` 與 `has_pending_work` 的語意不變。
- 取消與換輪：`flush_talk` 在鎖內清空佇列與暫存並遞增 epoch；合成完成時 epoch 已變就丟棄，發聲時每一幀檢查 epoch、引擎狀態與 `parent.accepts_media(…, "tts_held_fragment")`（ADR 0007 的輪次柵欄），所以被取消或被取代的輪次不會播出舊暫存。讀佇列與 epoch 在同一把鎖內，避免舊輪的文字配上新輪的 epoch。
- 失敗：暫存片段合成失敗時保留錯誤，輪到該片段才回報 `tts_exhausted_before_audio`，不提前打斷正在播放的前一片；後續片段照常播放。
- 不變：每個模型的合成鎖、`length_scale`、`noise_scale`、執行緒數、`txt_to_audio`（不預取的單片路徑）。
- 測試（`tests/test_matcha_tts.py`，假合成器、無模型、無 GPU）：用模擬音訊時鐘量到片段間隔（修正前 154 ms，修正後低於 50 ms）；預取只領先 1 片；flush 時暫存與合成中片段不會播出；輪次被取代但沒有 flush 時暫存片段也不播；失敗片段依序回報；兩個引擎共用同一聲線模型時合成仍一次一段。移除 epoch 與狀態檢查的變異測試會使測試失敗。
- CI：基準（matcha-training 尖端）與修改後都是 ruff、pyright、`scripts/check-integration.py`、`uv lock --check` 通過；pytest 基準 2 failed、1564 passed、3 skipped，修改後 2 failed、1571 passed、3 skipped（同樣兩個既有失敗：PDF OCR、role coordinator；新增 7 個測試，無新增跳過）。未動 `web/`，前端步驟未跑。
- 尚未驗證（驗收需實機）：Matcha 片段間隔實際降到約 20–50 ms，與舞台是否仍有跳音。檢查方式：用 Matcha 聲線連續對話一段會切成多片的長回覆，從日誌比對片段之間的空白（修正前 221–280 ms）；若仍聽到跳音，依本工單說明在 `put_audio_frame` 記錄逐幀時間與 `media_sequence`、同時錄 WebRTC 輸出，另開工單。
