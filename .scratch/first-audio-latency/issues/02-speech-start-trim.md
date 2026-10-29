<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 開口前待機靜音修剪回歸
Status: ready-for-agent

依[規格](../spec.md)。`src/utils/webrtc.py:583` 的 `prepare_speech_start` 在佇列頭的音訊帶有 metadata 時停止修剪；自 commit 65ee282（2026-10-17）起待機音訊一律帶 `avatar_epoch`（`src/avatars/base.py:560`），所以修剪從未再發生（日誌中「speech start trimmed」至 10/16 17:22 共 998 次，之後為 0），開口前多播 9–11 幀（約 0.2 s）待機音訊。

修正為只把「屬於回覆的 metadata」視為停止點，`avatar_epoch` 這類待機標記不算。完成：回歸測試先失敗後通過；量測工具顯示片段到 WebRTC 送出縮短約 0.15–0.2 s。

## Comments
