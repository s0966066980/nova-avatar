<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 渲染執行緒停止、echo 修正與 pyright
Status: resolved
Blocked by: 12

依[規格](../spec.md)。

- `src/utils/webrtc.py:600-607` 在 event loop 上無逾時 join 渲染執行緒。Wav2Lip（`:257-260`）／UltraLight（`:296-299`）先 join infer 執行緒再設 quit event，infer 卡在無逾時 `res_frame_queue.put` → 斷線即永久死鎖；MuseTalk 每次斷線卡約 1 秒。改為先設 quit event，`await asyncio.to_thread(t.join, timeout)`；queue `put` 加逾時。
- 渲染執行緒無例外防護（`src/avatars/musetalk/avatar.py:587-677`、`src/avatars/base.py:483-618`）：`render()` 以 try/finally 保證設 quit event；`process_frames` 出錯時結束說話狀態。
- `src/server/routes/chat.py:32-38`：非角色 echo 路徑使用未定義的 `started` → 已唸出卻回報失敗，重試唸兩次。修正回應。
- 守門：加入 pyright（dev 依賴、固定版本），對 `src/server` 只開 `reportPossiblyUnbound`（及 pyright basic 中可零誤報通過者），加進 CI。

完成：斷線不阻塞其他請求、echo 回傳成功的回歸測試；pyright 對 chat.py 舊碼報錯、修正後綠；完整 CI 通過。

## Comments

### 2026-10-29 實作結果

- `HumanPlayer._stop`：先設 quit event，再以 `asyncio.to_thread(join, RENDER_THREAD_JOIN_TIMEOUT=5s)` 在背景等待渲染執行緒；逾時記 warning 後放棄，不再卡住 event loop。`player.render_stopped` 可等待收尾完成。
- Wav2Lip／UltraLight／MuseTalk `render()` 改為 try/finally：先設外層、infer、process 三個 quit event，再 join 已啟動的工作執行緒；迴圈出錯也會停止 TTS 與工作執行緒。
- Wav2Lip／UltraLight inference 的 `res_frame_queue.put` 改用 `base.put_until_quit`（每 0.1 秒檢查 quit event）。
- `process_frames`：單幀例外記錄後結束說話狀態並繼續；執行緒結束時一律 `speaking=False`。
- `chat.py`：非角色 echo 移除未定義的 `**started`，回傳 `code: 0`。
- pyright `1.1.414`（dev 群組，已更新 `uv.lock`）：`[tool.pyright]` 只檢查 `src/server`，basic 模式加 `reportPossiblyUnboundVariable=error`（`reportPossiblyUnbound` 在此版已改名），關閉目前仍有既有債務的 6 條規則與依安裝環境而定的 import 規則。舊版 chat.py 被 `reportUnboundVariable` 抓到，修正後 0 錯誤。CI 新增 `uv run --no-sync pyright`，並更新 `docs/current-project-workflow.md`。
- 回歸測試：`tests/test_render_stop.py`（7 項）。驗證：ruff、pyright、check-integration、pytest（905 passed、3 skipped，排除 2 項已知 worktree 基準失敗）、web lint/test/build 全數通過。
