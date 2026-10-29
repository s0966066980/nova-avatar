<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 開口前待機靜音修剪回歸
Status: resolved

依[規格](../spec.md)。`src/utils/webrtc.py:583` 的 `prepare_speech_start` 在佇列頭的音訊帶有 metadata 時停止修剪；自 commit 65ee282（2026-10-17）起待機音訊一律帶 `avatar_epoch`（`src/avatars/base.py:560`），所以修剪從未再發生（日誌中「speech start trimmed」至 10/16 17:22 共 998 次，之後為 0），開口前多播 9–11 幀（約 0.2 s）待機音訊。

修正為只把「屬於回覆的 metadata」視為停止點，`avatar_epoch` 這類待機標記不算。完成：回歸測試先失敗後通過；量測工具顯示片段到 WebRTC 送出縮短約 0.15–0.2 s。

## Comments

### 2026-10-30 實作（分支 `fal/02-speech-start-trim`）

- `src/utils/webrtc.py`：新增 `_is_reply_metadata`；只含 `avatar_epoch`（`IDLE_MEDIA_MARKER_KEYS`）的 metadata 視為待機幀，`None` 亦同；其他 dict 或非 dict 仍視為回覆並停止修剪，行為與回歸前一致。
- 回歸測試（`tests/test_speech_timing.py`）：`test_speech_start_trims_idle_frames_tagged_with_avatar_epoch`（帶 `avatar_epoch` 的待機幀被修剪到 ≤ 1 幀跑道）、`test_speech_start_keeps_queued_reply_audio`（帶 `turn_id` 的回覆音訊不被丟棄）。修正前兩者皆失敗（佇列維持 0.24 s），修正後通過。
- CI：ruff、pyright 0 錯、`check-integration.py` 全部通過；pytest 1085 通過、3 略過，2 失敗為 worktree 缺少 gitignored 資產的已知基準失敗。

待實機驗證（需以新程式重啟後端，由協調者執行）：
1. 重啟後進行數輪舞台語音對話，`grep -c "speech start trimmed" logs/start-all-backend.log` 應在每輪開口時增加（10/17 後一直為 0）。
2. 以 issue 01 的量測工具比較「片段到第一個 WebRTC 音訊送出」，P50 預期較基準縮短約 0.15–0.2 s。
