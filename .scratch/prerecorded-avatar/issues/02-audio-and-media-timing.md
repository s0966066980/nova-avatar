<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->

# 預錄模式音訊管線與媒體時序

Status: ready-for-agent
Type: task
Blocked by: 01

預錄模式只使用對話音訊與事件，不載入 MuseTalk 嘴型資源；補齊可
對齊接收端 WebRTC 語音的媒體時序，讓影片跟隨實際回答播放。
依 [ADR-0016](../../../docs/adr/0016-separate-prerecorded-presentation-and-asset-production.md)
保留伺服器的輪次、發話與音訊主時鐘責任。

## 責任範圍

`src/avatars/factory.py`、`src/server/app.py`、`src/server/routes/webrtc.py`、
`src/utils/webrtc.py`、`src/server/voice_session.py` 與獨立音訊輸出實作。

## 驗收

- 預錄啟動／切換／就緒不要求非空嘴型模型，不呼叫其載入或預熱。
- LLM、TTS、收音、歷史與片段提交行為使用原有對話契約。
- 先用最小可驗證實驗建立伺服器時序與接收端聲音的對齊證據，再
  接正式影片切換；不以事件到達時間或前端音量猜測冒充權威時序。
- 事件包含會話、輪次、generation、單調序號及所需媒體時間資訊；
  靜音逾 300 ms 的視覺規則不提前恢復收音或提交輪次。
- 取消、錯誤與斷線後排定的舊事件失效，不復播舊語音／影格。
- 控制台與舞台保留獨立的會話和時鐘，不加入跨會話回答同步。

## 驗證

涵蓋音訊無嘴型依賴的啟動／切換、自然停頓、TTS 長停頓、插話、
generation 失效與斷線。真實瀏覽器記錄接收 PCM、事件與視覺切換
時間差；若無法可靠對齊，記錄限制並修正設計，不靜默替換為 RMS。

## Comments

2026-10-12：這是瀏覽器呈現前的關鍵技術驗證；尚無達標證據。

2026-10-13：使用者已授權開始實作；程式已接入，正在完成實機驗收與回歸。

實作：預錄啟動不載入嘴型模型，沿用直接 PCM 與輪次隔離；64×32 RTP 時鐘對齊接收端素材活動事件。

2026-10-13 驗證結果：實作與回歸完成，已在控制台接入並完成實機播放、素材製作與錄影驗證。詳見 ../validation/README.md。
