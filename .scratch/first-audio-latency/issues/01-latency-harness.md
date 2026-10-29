<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 量測工具與基準線
Status: ready-for-agent

依[規格](../spec.md)。`scripts/replay_voice_baseline.py` 與 `scripts/benchmark_streaming_vs_legacy.py` 使用模擬時鐘，不是實測；`webrtc_video_enqueue` 指標恆為 0；主回答前的路由、檢索、模型資訊查詢沒有任何指標（`src/server/voice_session.py:843-952` 之前段）。

- 擴充 `scripts/run_voice_soak.py`（或新增工具）：以固定錄音經真實 WebRTC 送入舞台工作階段，回報**感知首音延遲**（錄音中人聲實際結束 → 第一個非靜音回覆音訊幀）、首音延遲（VAD 判定說完起算）、「伺服器接受 Prompt」起算延遲，以及各階段：VAD 靜音等待、辨識、路由、檢索、模型資訊查詢、主回答首 token、第一個可播片段、TTS 首段音訊、第一批渲染、WebRTC 送出。輸出 P50／P95 JSON。
- `src/server/reply_streaming/metrics.py` 補上主回答前各段指標；修正 `webrtc_video_enqueue`。
- 錄音集：一般、RAG、需交接各至少 10 句，中英文皆有；不保存使用者錄音（ADR 0004），使用合成或授權錄音。
- 以目前設定量出基準線，結果存 `.scratch/first-audio-latency/baseline-<日期>.json`，並在 Comments 摘要。

完成：工具在本機實跑通過；與日誌推算的現況同一量級；有單元測試涵蓋統計與階段對齊。

## Comments
