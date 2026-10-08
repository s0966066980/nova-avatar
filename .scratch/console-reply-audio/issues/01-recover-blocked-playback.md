<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 控制台恢復受阻的回覆語音播放

Status: resolved
Type: task

## 問題與診斷

使用者回報控制台聽不到數字人語音。對本機正在執行的 Edge TTS＋MuseTalk
服務，以固定文字朗讀建立真實 WebRTC 接收端，確認收到非靜音音訊
（解碼 RMS 最高約 1203）。

Chromium 153 的一般播放政策可以正常播放；以
`--autoplay-policy=user-gesture-required` 啟動的全新瀏覽器則可重現播放器
`paused=true`、已連線卻沒有語音的情況。使用者原本的瀏覽器與播放政策尚未確認，
因此這項診斷只確認了播放受阻這條可重現路徑。

控制台原先只依賴 `autoplay`，沒有處理播放被拒絕或提供手動恢復操作；
音訊軌與視訊軌分別到達時還會重複設定同一個 `srcObject`。

## 修正

- 每次連線只綁定一次媒體串流，軌道抵達後主動嘗試播放。
- 回報播放、暫停與靜音狀態；受阻時提供「啟用聲音」按鈕。
- 按鈕直接在使用者點擊內呼叫播放，並解除播放器靜音與零音量。
- 舊連線的播放 Promise 不得改變新連線狀態；斷線時清除播放事件。

## 驗證（2026-10-06）

`cd web && node --test tests/reply-playback.test.js tests/useWebRTC.test.js`
修正前新增回歸測試失敗，修正後 8 項通過。

真實瀏覽器在嚴格播放政策下，按下新增按鈕後 `paused=false`、
`muted=false`、`volume=1`，接收音訊能量約 0.063。
一般政策下也通過，接收音訊能量約 0.162。

- `npm test`：87 項通過。
- `npm run build`：通過。
- `uv run --no-sync python scripts/check-integration.py`：品牌、授權與整合稽核通過。
- `uv run --no-sync pytest`：505 通過、4 略過、1 失敗。
  失敗的是本次未修改的背景合成效能測試：全套執行約 46 ms、單獨重跑約
  37 ms，均超過 30 ms 門檻；沒有調整測試門檻或背景合成實作。
