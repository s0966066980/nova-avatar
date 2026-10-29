<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 不阻塞 event loop
Status: resolved
Blocked by: 03

依[規格](../spec.md)「輸入限制原則」。

- `/asr`（`src/server/routes/audio.py:58-61` → `src/vad/audio.py:51`）：`sf.read` 先完整解碼（8 MB FLAC 可膨脹到約 20 GB），session 檢查在解碼之後。改為先查 session，以 `sf.info` 檢查時長上限，再於 `to_thread` 解碼。
- `/asr` 未傳 `config`，ASR 快取 key 與 session 不一致（`routes/audio.py:71-78` vs `src/asr/factory.py:58-66`），每次呼叫同步重載 faster-whisper。修正 key。
- `/humanaudio`（`routes/audio.py:18-23` → `src/avatars/base.py:335-344`）：解碼與重採樣進 `to_thread` 並設時長上限；不可在 loop 執行緒上 `time.sleep` 等佇列。
- 背景圖（`src/scene/service.py:62-79`）：先以 Pillow 只讀標頭檢查像素數再交給 `cv2`；接住 `DecompressionBombError` 回 400。
- 錄影（`src/server/routes/video.py:82-84` → `src/avatars/base.py:690-747`）：`os.system` 以 shell 合併改為 `asyncio.create_subprocess_exec` argv；ffmpeg `wait()` 不在 loop 上；session 關閉時停止錄影並清除暫存。

完成：每項的回歸測試（含 loop 在處理期間仍能回應另一請求）；完整 CI 通過。

## Comments

### 2026-10-29 實作結果（分支 `sh/09-event-loop`）

- `/asr`：先查 session（不存在回 404，不解碼）；`ensure_audio_within` 在 `to_thread` 以 `sf.SoundFile` 標頭 frame 數先擋（上限 60 秒，回 413），讀取最多 limit+1 frame；soundfile 讀不了的格式改由 PyAV 先看 container duration、解碼時累計樣本超限即中止。VAD、ASR 載入、轉寫、LLM 全進 `to_thread`。
- ASR 快取 key：改傳 `config=state.config`，與 voice session／prewarm 同 key；語言改為每次呼叫的 `transcribe(language=...)`，不再改動共用辨識器。
- `/humanaudio`：先查 session；`put_audio_file`（解碼、重採樣、佇列等待）整個進 `to_thread`；標頭超過 300 秒回 413。
- 背景圖：Pillow 只讀標頭檢查像素數再交給 cv2；`DecompressionBombError` 轉 `SceneError` 回 400；影片先看 capture 寬高。順帶修正：上傳暫存檔沒有副檔名，原本圖片／GIF 都走 `VideoCapture`，現依原始檔名選解碼器。
- 錄影：暫存檔改放 `tempfile.mkdtemp`；停止時 ffmpeg `wait()` 在 `to_thread`（逾時 kill），合併改 `asyncio.create_subprocess_exec` argv（逾時或取消會 kill）；寫入 pipe 加鎖、改 `tobytes()`、首幀到達時才啟動 ffmpeg（原本未啟動會 AttributeError）。WebRTC cleanup 呼叫 `discard_recording()` 停止錄影並刪除暫存。`/download` 與錄影共用 `RECORDS_DIR`。
- 測試：新增 `tests/test_event_loop_blocking.py`（14 項，含 `/asr` decode／載入、`/humanaudio`、`/record` 處理中 `/health` 仍可回應）、`test_scene_background.py` 5 項、`test_webrtc_lifecycle.py` 1 項。完整 pytest 848 passed／2 failed（worktree 已知基線）、ruff、check-integration、web lint／test（199）／build 皆通過。
