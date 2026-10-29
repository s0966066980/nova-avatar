<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 量測工具與基準線
Status: resolved

依[規格](../spec.md)。`scripts/replay_voice_baseline.py` 與 `scripts/benchmark_streaming_vs_legacy.py` 使用模擬時鐘，不是實測；`webrtc_video_enqueue` 指標恆為 0；主回答前的路由、檢索、模型資訊查詢沒有任何指標（`src/server/voice_session.py:843-952` 之前段）。

- 擴充 `scripts/run_voice_soak.py`（或新增工具）：以固定錄音經真實 WebRTC 送入舞台工作階段，回報**感知首音延遲**（錄音中人聲實際結束 → 第一個非靜音回覆音訊幀）、首音延遲（VAD 判定說完起算）、「伺服器接受 Prompt」起算延遲，以及各階段：VAD 靜音等待、辨識、路由、檢索、模型資訊查詢、主回答首 token、第一個可播片段、TTS 首段音訊、第一批渲染、WebRTC 送出。輸出 P50／P95 JSON。
- `src/server/reply_streaming/metrics.py` 補上主回答前各段指標；修正 `webrtc_video_enqueue`。
- 錄音集：一般、RAG、需交接各至少 10 句，中英文皆有；不保存使用者錄音（ADR 0004），使用合成或授權錄音。
- 以目前設定量出基準線，結果存 `.scratch/first-audio-latency/baseline-<日期>.json`，並在 Comments 摘要。

完成：工具在本機實跑通過；與日誌推算的現況同一量級；有單元測試涵蓋統計與階段對齊。

## Comments

### 2026-10-30 實作（分支 `fal/01-latency-harness`）

- 指標（`src/server/reply_streaming/metrics.py`）：新增階段 `pre_answer`（辨識結果進入回覆流程 → 主回答開始或固定回覆送出，含 `routing`、`retrieval`）、`routing`、`retrieval`、`model_info`（llama-server `/props`、`/apply-template`、`/tokenize` 預檢，屬 `llm_first_token` 之內）；新增 `prompt_first_audio_seconds`（伺服器接受 Prompt 起算）。`model_info` 在 LLM 工作執行緒以 `timed_stage` 計時，經 `loop.call_soon_threadsafe` 寫回該輪（CODING_STANDARDS 第 2 條）。
- 修正 `webrtc_video_enqueue`：只在含回覆音訊的批次送出影像時完成；帶 `avatar_epoch` 的待機幀不再觸發（`src/avatars/base.py`）。
- 工具 `scripts/measure_first_audio.py`：以舞台身分（loopback，ADR 0021 舞台類路由 `POST /offer`）建立真實 WebRTC，記憶體內合成固定語句並即時送出；用戶端記錄錄音人聲實際結束時刻（`PushAudioTrack` 送出標記）與第一個非靜音回覆音訊幀，合併伺服器 `turn_metrics`。交接輪次等待接手角色回覆完成再進下一句，另報接手首音。輸出各類別（all／general／rag／handoff）P50／P95、全部階段、對齊統計與規格目標判定；只寫 fixture ID 與數值。
- 錄音集（`src/server/reply_streaming/latency_baseline.py`）：一般 11、RAG 11、交接 10（5 組「轉天氣 → 轉回主角色」），中英文皆有；Edge TTS 記憶體合成，不存檔（ADR 0004）。RAG 句為通用知識庫問題，現場知識庫不符時以 `--fixtures <json>` 替換。
- 階段對齊：依序鏈 `asr + pre_answer + first_fragment + avatar_to_webrtc_commit` 對 `first_audio_seconds` 的殘差；用戶端感知值減伺服器估算（`vad_endpoint + first_audio_seconds`）須落在 −0.3～+0.6 s，否則視為誤歸屬（例如招呼語音），不計入感知 P50／P95 並計數。
- 測試：`tests/test_first_audio_latency.py` 31 項（統計、對齊、錄音集、交接流程與過期 `listening` 事件、新階段、`webrtc_video_enqueue`）。全套 1114 passed，僅已知 2 項 worktree 基準失敗；ruff、pyright、`check-integration.py` 通過。

### 待實機驗證

依實作指南不得在共用舞台建立 WebRTC 工作階段或重啟服務，基準線尚未量測，`Status` 維持 `ready-for-agent`。步驟（於合併後的程式碼）：

1. 以含本 ticket 的程式碼重啟後端（現行 8010 跑 `main`，舊程式碼下 `pre_answer`／`routing`／`retrieval`／`model_info`／`prompt_first_audio_seconds` 會是 `null`）。記下 llama-server 實際 `-ngl`（`grep "解除安裝" logs/nova-avatar_*.log | tail -1`）。
2. 關閉 kiosk 舞台頁（角色啟用時舞台只允許 1 個工作階段，否則 `/offer` 回 429）。
3. 在舞台主機執行：
   ```
   cd /home/oliver/nova-avatar
   .venv/bin/python scripts/measure_first_audio.py --rounds 1 --warmup 1 \
     --note "llama-server ngl=<N>; whisper small auto beam5; Qwen3.5-9B; Edge TTS; MuseTalk TRT" \
     --output .scratch/first-audio-latency/baseline-2026-10-30.json
   ```
   約 35 輪、10–15 分鐘。每輪印 `turn i/N <fixture> status=completed perceived=… first_audio=… handoff=…`，最後印各類別 P50／P95 與報告路徑；有失敗輪次時結束碼為 1。
4. 預期（與 10/29 日誌同量級，ngl 31）：general `first_audio_seconds` P50 約 3–4 s、`perceived_first_audio_seconds` 約再加 0.3–0.4 s；`pre_answer` P50 約 1.5 s（路由約 1.2 s、檢索約 0.7 s）；`model_info` 約 0.2–0.4 s；`webrtc_video_enqueue` 不再為 0。`misaligned_turns` 應為 0 或極少；`rag_status` 若多為 `empty`，以現場知識庫問題改用 `--fixtures` 重跑 RAG 類。
5. 將結果摘要（各類別感知／首音／Prompt 起算 P50／P95、主要階段）補在本 Comments，再設 `Status: resolved`。

### 2026-10-30 實機基準線（orchestrator）
`baseline-2026-10-30.json`：`main`＋本 issue 量測（commit 8d625f7），9B 全 GPU（`-ngl 99`）、Whisper small auto／beam 5、Edge TTS，32 輪全數完成、對齊 0 失敗。
感知首音延遲 P50／P95：一般 4.09／4.43 s、RAG 3.93／4.22 s、交接 2.48／2.69 s。一般輪次 P50 各段：VAD 靜音等待 0.32、辨識 0.41、主回答前 1.29（路由 0.69＋檢索 0.50，串行）、首片段 0.93、片段到 WebRTC 0.62 s。模型資訊查詢實測僅 0.03 s。
用戶端偏移（感知 − 伺服器估算）P50 0.37 s，未拆解，待 issue 14 說明。測試題的 RAG 問題與現場知識庫（僅一份文件）不符，21 輪中 20 輪檢索為空。
