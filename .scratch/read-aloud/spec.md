<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->

# 朗讀模式的聲音與嘴型斷續

使用者確認朗讀時聲音與嘴型都會斷續。先不用 LLM，修正正式朗讀
路徑，不能只用直接餵入 tagged PCM 的模型測試代替正式 HTTP 路由。

驗收：完整送出所有 TTS PCM、播放時間接近 PCM 原長、最大標記
音訊間隔小於 60ms、嘴型覆蓋率至少 95%、A/V P95 不超過 80ms。
使用真實模型、正式 `/offer` 與 `/human type=echo`、H.264 WebRTC
接收解碼。保留近似解碼的明確選用與畫質取捨，不改保存的偏好。

狀態：正式朗讀路徑已通過上述驗收；瀏覽器與實際喇叭需以相同
加速設定確認。結果與全套檢查見 [report.md](report.md)。
