<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 不阻塞 event loop
Status: ready-for-agent
Blocked by: 03

依[規格](../spec.md)「輸入限制原則」。

- `/asr`（`src/server/routes/audio.py:58-61` → `src/vad/audio.py:51`）：`sf.read` 先完整解碼（8 MB FLAC 可膨脹到約 20 GB），session 檢查在解碼之後。改為先查 session，以 `sf.info` 檢查時長上限，再於 `to_thread` 解碼。
- `/asr` 未傳 `config`，ASR 快取 key 與 session 不一致（`routes/audio.py:71-78` vs `src/asr/factory.py:58-66`），每次呼叫同步重載 faster-whisper。修正 key。
- `/humanaudio`（`routes/audio.py:18-23` → `src/avatars/base.py:335-344`）：解碼與重採樣進 `to_thread` 並設時長上限；不可在 loop 執行緒上 `time.sleep` 等佇列。
- 背景圖（`src/scene/service.py:62-79`）：先以 Pillow 只讀標頭檢查像素數再交給 `cv2`；接住 `DecompressionBombError` 回 400。
- 錄影（`src/server/routes/video.py:82-84` → `src/avatars/base.py:690-747`）：`os.system` 以 shell 合併改為 `asyncio.create_subprocess_exec` argv；ffmpeg `wait()` 不在 loop 上；session 關閉時停止錄影並清除暫存。

完成：每項的回歸測試（含 loop 在處理期間仍能回應另一請求）；完整 CI 通過。

## Comments
