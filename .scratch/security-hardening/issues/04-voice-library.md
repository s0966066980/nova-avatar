<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# TTS 參考音訊庫與路徑限制
Status: resolved
Blocked by: 03

依[規格](../spec.md)「輸入限制原則」。`POST /api/speech/tts` 接受任意 `ref_file` 與 `tts_server`；xtts 預覽會把該檔上傳到 `{tts_server}/clone_speaker`（`src/server/runtime_settings.py:1468-1625`、`src/tts/engines/xtts.py:33`；fish、indextts2、cosyvoice 同類），可外洩 `config/ragflow.env`。`model` 接受任意目錄交給 CosyVoice `AutoModel`（`runtime_settings.py:1529` → `scripts/cosyvoice_fastapi_server.py:256`）。`/api/speech/path-picker` 在 event loop 開 tkinter（`src/server/routes/settings.py:389`）。

- 刪除 path-picker 路由、handler 與前端按鈕。
- 參考音訊庫：上傳 → 驗證為音訊並轉 WAV → 存 `data/voices/<id>.wav`；列表、刪除端點（管理類）。`ref_file` 只接受庫內 ID；既有設定中的路徑在載入時若位於允許根目錄內則遷移，否則清空並記錄。
- `model` 只接受 `models/` 掃描出的清單；`tts_server` 只接受 loopback host。
- `xtts.py`、`fish.py`：所有 `requests` 加 `timeout=`，檔案以 `with` 開啟；`indextts2.py` client 設逾時。
- 控制台 TTS 設定改為從音訊庫選擇與上傳。

完成：以 `/etc/passwd` 或 `config/*.env` 為 `ref_file`、外部 URL 為 `tts_server` 的請求被拒的回歸測試；完整 CI 通過。

## Comments

### 2026-10-29 實作結果（分支 `sh/04-voice-library`）

- 新增 `src/tts/voice_library.py`：上傳以魔術位元組判定容器並明確指定 FFmpeg demuxer（不讓它探測 HLS／concat 播放清單），先讀標頭檢查時長（上限 60 秒、20 MB），再解碼成單聲道 WAV 存 `data/voices/<id>.wav`；ID 取自音訊內容雜湊，重複上傳得到同一 ID。刪除改為移入 `data/voices/.deleted/` 回收桶，使用中（目前設定或任一角色設定檔）回 409。
- 新路由 `GET/POST /api/speech/voices`、`DELETE /api/speech/voices/{voice_id}`，皆列為管理類；`/api/speech/path-picker` 路由、handler 與前端按鈕（含 STT 的「選擇資料夾」）已刪除。
- `ref_file`：需參考音檔的引擎（gpt-sovits、xtts、indextts2、cosyvoice 系列）只接受音訊庫 ID；Edge／Fish 只接受伺服器端聲線名稱（英數、底線、連字號）。`tts_server` 只接受 loopback（127.0.0.1、localhost、::1），並拒絕帳密、路徑、查詢參數。`model` 只接受 `models/` 掃描出的 CosyVoice 模型（依 `cosyvoice2.yaml`／`cosyvoice3.yaml` 判定家族），空白沿用預設位置。
- `POST /api/speech/tts` 在延後套用（有連線時存 pending）之前就先驗證，不安全的請求一律 400、不會寫入 pending。角色設定檔的 `tts` 也套用相同規則。
- 載入時遷移：`load_config` 與角色設定檔讀取時，位於 `data/` 或 `~/CosyVoice/asset` 內的既有路徑移入音訊庫，其餘清空並記錄警告；外部 `tts_server`、非清單 `model` 同樣清空。
- 引擎：`xtts.py`、`fish.py` 所有 `requests` 加 `timeout=(5, 60)`，xtts 以 `with` 開檔並只上傳音訊庫檔案；`indextts2.py` 的 Gradio client 設 `httpx_kwargs` 逾時，預測改 `submit().result(timeout=120)`；sovits、cosyvoice 也改由音訊庫 ID 解析路徑。
- 控制台 TTS 設定改為從音訊庫下拉選擇、上傳與刪除；模型改為清單選擇；角色設定檔編輯器的參考音檔也改為音訊庫下拉。
- 測試：新增 `tests/test_voice_library.py`（86 項，含 `/etc/passwd`、`config/*.env` 為 `ref_file`、外部 URL 為 `tts_server`、`/tmp` 為 `model` 的 HTTP 回歸測試）。Python 914 passed、3 skipped，僅兩項已知的工作樹基線失敗；ruff、check-integration、前端 lint／200 項測試／build 皆通過。
- 未處理：音訊庫回收桶尚無復原介面；刪除時未檢查 pending 設定是否引用該音訊（套用時會因驗證失敗而顯示錯誤）；FunASR 的 `model_size` 仍接受任意字串（屬 STT，不在本票範圍）。
