<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# TTS 參考音訊庫與路徑限制
Status: ready-for-agent
Blocked by: 03

依[規格](../spec.md)「輸入限制原則」。`POST /api/speech/tts` 接受任意 `ref_file` 與 `tts_server`；xtts 預覽會把該檔上傳到 `{tts_server}/clone_speaker`（`src/server/runtime_settings.py:1468-1625`、`src/tts/engines/xtts.py:33`；fish、indextts2、cosyvoice 同類），可外洩 `config/ragflow.env`。`model` 接受任意目錄交給 CosyVoice `AutoModel`（`runtime_settings.py:1529` → `scripts/cosyvoice_fastapi_server.py:256`）。`/api/speech/path-picker` 在 event loop 開 tkinter（`src/server/routes/settings.py:389`）。

- 刪除 path-picker 路由、handler 與前端按鈕。
- 參考音訊庫：上傳 → 驗證為音訊並轉 WAV → 存 `data/voices/<id>.wav`；列表、刪除端點（管理類）。`ref_file` 只接受庫內 ID；既有設定中的路徑在載入時若位於允許根目錄內則遷移，否則清空並記錄。
- `model` 只接受 `models/` 掃描出的清單；`tts_server` 只接受 loopback host。
- `xtts.py`、`fish.py`：所有 `requests` 加 `timeout=`，檔案以 `with` 開啟；`indextts2.py` client 設逾時。
- 控制台 TTS 設定改為從音訊庫選擇與上傳。

完成：以 `/etc/passwd` 或 `config/*.env` 為 `ref_file`、外部 URL 為 `tts_server` 的請求被拒的回歸測試；完整 CI 通過。

## Comments
