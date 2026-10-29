<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 片段與渲染路徑的等待
Status: ready-for-agent
Blocked by: 01, 02

依[規格](../spec.md)。片段到 WebRTC 送出 P50 0.62 s：

- MuseTalk 待機時 sleep 約 160–190 ms（`src/avatars/musetalk/avatar.py:669`），開口時無法立即喚醒；未滿批次最多保留 0.35 s。改為有回覆音訊時立即喚醒、第一批不等滿批。
- 每輪與打斷後固定等待 0.3 s：確認是否在首音路徑上，在則移除。
- 以 issue 01 工具量測每項改動的效果，未改善者撤回。

## Comments

### 2026-10-30 實作（分支 `fal/13-media-waits`）

三項改動各自一個 commit，可單獨 `git revert`：

| 改動 | commit | 內容 |
|---|---|---|
| A 待機節流可喚醒 | `a923c15` | `src/avatars/musetalk/avatar.py` 待機時的 `time.sleep(0.04*qsize*0.8)`（約 160–190 ms）改為 `audio_stream.wait_for_audio(...)`；`put_audio_frame` 放入回覆音訊即喚醒（`src/avatars/audio_stream_handler.py`）。 |
| B 每輪第一批用啟動批次 | `8d12e9f` | `src/avatars/musetalk/audio_stream_handler.py` 以 `(turn_id, generation)` 追蹤最後一個說話批次的輪次；新輪次第一批改為啟動批次（4 幀影像／8 幀音訊），渲染迴圈只等 8 幀而非 16 幀、最多 0.35 s。原本只有中斷後的第一輪會重建說話前瞻（lookahead），之後各輪第一批前面帶 10 幀（200 ms）待機前瞻；現在每輪都以自己的語音前瞻開頭。前瞻等待加上 `max_tts_audio_wait_seconds` 上限，TTS 卡住時不凍結待機影像。 |
| C 取代輪次不等 0.3 s | `691a054` | `src/server/voice_session.py` `_interrupt_locked(tail_guard=False)`：文字輪次或朗讀輪次中斷進行中（含尾端保護中）的輪次時，不再等 0.3 s，因為新輪次會立刻關閉收音。單純中斷（按鈕、`cancel_text_request`）仍保留 0.3 s。 |

0.3 s 是否在首音路徑上：
- `_finish_tail_guard` 的 0.3 s：語音輪次不在路徑上（下一輪要等收音重開後才開始說話，首音從說完起算）。未改。
- `_interrupt_locked` 的 0.3 s：文字輪次與朗讀輪次在前一輪播放中或結束後 0.3 s 內送出時，這 0.3 s 落在「伺服器接受 Prompt」（`mark_speech_end`）**之前**，所以 `prompt_first_audio_seconds` 看不到，但使用者感受得到。已移除（改動 C）。

測試：`tests/test_realtime_avatar.py` 新增待機喚醒、每輪啟動批次、前瞻等待上限、渲染迴圈不等滿批 4 項，並更新 3 項原本固定「第一批為完整批次」的斷言；`tests/test_voice_session.py` 新增 2 項（取代輪次不等待、單純中斷保留 0.3 s）。全套 1140 passed、3 skipped，僅已知 2 項 worktree 基準失敗；ruff、pyright、`check-integration.py` 通過。

### 待實機驗證

依實作指南不得在共用舞台建立 WebRTC 工作階段或重啟服務，三項改動的實機效果尚未量測，`Status` 維持 `ready-for-agent`。ticket 01 的基準線也還沒量。步驟：

1. 基準：在 `first-audio-latency`（不含本 ticket）重啟後端，執行
   `.venv/bin/python scripts/measure_first_audio.py --rounds 1 --warmup 1 --note "fal13 base" --output .scratch/first-audio-latency/fal13-base.json`
   （ticket 01 的基準線若已用同一設定量過，可直接沿用）。
2. 依序只多套一項改動後重啟後端並重跑同一指令（`--note "fal13 +A"` 等），輸出 `fal13-A.json`、`fal13-AB.json`、`fal13-ABC.json`：
   - A：看 `stages.avatar_to_webrtc_commit` 與 `musetalk_first_batch` 的 P50／P95，預期降低最多約 0.1–0.19 s（片段到達時渲染迴圈正在待機節流的輪次）。
   - B：同上兩項加 `musetalk_inference_first_result`，預期第二輪起首批推論變短、`avatar_to_webrtc_commit` 降低；同時目視舞台確認開口第一幀嘴型與聲音對齊、TTS 慢時待機影像不凍結。
   - C：量測工具只送語音，不受影響。另在主控台前一輪仍在播放時送出文字問題，以瀏覽器 DevTools 看 `POST /human` 回應時間：改前 ≥ 0.3 s，改後應 < 0.05 s。
3. 任何一項的 P50 沒有改善（或 B 造成嘴型不同步／影像凍結）就 `git revert` 該 commit，並把各次量測摘要補在本 Comments。
