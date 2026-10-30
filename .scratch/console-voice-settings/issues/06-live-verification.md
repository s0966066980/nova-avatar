<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 實機驗證與收尾
Status: ready-for-agent
Blocked by: 01, 02, 03, 04, 07

依[規格](../spec.md)。orchestrator 執行：Fun-ASR-Nano 與 Whisper GPU 比較並決定選單標註；以 BreezyVoice 測試音檔套用設定檔、試聽；控制台在 1920×1080、1280×720 實際瀏覽器截圖檢查；首音延遲最終量測並更新 `docs/project-status.md` 數字（承接 first-audio-latency）。

## Comments

### 2026-10-30 Code review 修正（分支 `cvs/review-fixes`）

逐項以失敗測試先行再修正：

1. **VAD「最小靜音判定時間」**：滑桿原綁 `vadDraft.min_silence_duration_ms`（伺服器不認得，拖動無效也不顯示），改綁 `min_silence_ms`；刻度改為 128–1504 ms、每格 32 ms（Silero 幀），192 ms＝6 格可選，數值即時顯示。測試：`web/tests/settings-organization.test.js`。
2. **設定檔編輯器試聽**（spec Q5）：「聲音與工具」新增「試聽此設定檔的聲音」，以編輯中（未儲存）的引擎與聲線合成「您好，歡迎光臨，很高興為您服務。」並自動播放。BreezyVoice 伺服器未就緒時先顯示「伺服器啟動中」並自動啟動；對話連線中不啟動新伺服器（409），也不取代預設聲音正在用的 BreezyVoice 伺服器（409，請先套用或用相同模型與服務網址）。新路由 `GET /api/speech/breezyvoice/status`、`POST /api/speech/preview` 皆列入 `ROUTE_ACCESS` 為 ADMIN；欄位只收音訊庫 ID、`models/` 清單 ID 與本機服務網址；啟動與合成在 `asyncio.to_thread`；`cosyvoice_runtime.ensure_server` 加鎖，試聽與套用同時啟動時只會開一個程序。測試：`tests/test_profile_voice_preview.py`、`web/tests/voice-selection.test.js`。
3. **逐字稿單一來源**：BreezyVoice 只用音訊庫逐字稿；設定檔與設定檔案中殘留的 `tts.ref_text` 於載入（啟動遷移）與儲存時清除並記錄 warning，也不再能代替缺少的音訊庫逐字稿。
4. **`_resource_key`** 納入 BreezyVoice 的模型與服務位址（預設值正規化）：連線中變更會延後到斷線後套用並啟動該伺服器，不再未啟動就發布為預設。
5. **即時組合**：兩位角色使用 BreezyVoice 時須同一模型與服務網址（參考音檔可不同），否則套用時顯示說明（409）。
6. **Fun-ASR-Nano 服務**：IPv6 主機加方括號（BreezyVoice 的 `server_url` 同步修正）；`stop_server()` 取消進行中的啟動（約 1–3 秒內結束），不再等 `_lock` 最多 300 秒。
7. **`apply_stt_settings`**：FunASR 無法使用時 `missing_package` 回報實際缺少的 venv 或權重與處理指令。
8. **重複定義**：輸出字元集清單與服務名稱只在 `src/asr/fun_asr_nano_service.py` 定義，引擎與設定頁共用；獨立 venv 的 `scripts/fun_asr_nano_server.py` 無法匯入 `src`，保留同值並由測試鎖定一致。
9. `spec.md` Q11 改為「不執行任何遠端程式碼（`trust_remote_code=False`）」。

已知缺口（本次不處理）：FunASR 辨識結果不提供信心分數；`deferred_settings.py` 寫檔未 fsync（既有問題）。

**新增待實機驗證**（不需 GPU 的部分已單元測試）：
- 後端未連線時，在控制台設定檔編輯器（BreezyVoice、選有逐字稿的音檔）按「試聽此設定檔的聲音」：伺服器未啟動時應先顯示「BreezyVoice 伺服器啟動中」，約 1–2 分鐘後自動播放試聽句；`logs/cosyvoice-server.log` 出現啟動紀錄。再按一次應直接顯示「合成試聽句中」並在數秒內播放。
- 舞台連線中再試聽同一模型：可播放；改填其他服務網址試聽：顯示需斷線（409），舞台聲音不中斷。
- Edge TTS 角色試聽：數秒內播放所選聲線。
- 「訪客互動與語音辨識」頁把最小靜音判定時間拖到 192 ms 儲存，`GET /api/vad` 回 `min_silence_ms: 192`，`config/runtime_overrides.yaml` 更新。
- 兩個控制台分頁：A 分頁套用 FunASR，啟動完成前在 B 分頁套用 Whisper。B 應在 Whisper 載入後即完成（不等 FunASR 啟動），A 顯示「Fun-ASR-Nano 啟動已取消」，`ss -lptn 'sport = :50010'` 無殘留程序。
