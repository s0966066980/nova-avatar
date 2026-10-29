<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 渲染執行緒停止、echo 修正與 pyright
Status: ready-for-agent
Blocked by: 12

依[規格](../spec.md)。

- `src/utils/webrtc.py:600-607` 在 event loop 上無逾時 join 渲染執行緒。Wav2Lip（`:257-260`）／UltraLight（`:296-299`）先 join infer 執行緒再設 quit event，infer 卡在無逾時 `res_frame_queue.put` → 斷線即永久死鎖；MuseTalk 每次斷線卡約 1 秒。改為先設 quit event，`await asyncio.to_thread(t.join, timeout)`；queue `put` 加逾時。
- 渲染執行緒無例外防護（`src/avatars/musetalk/avatar.py:587-677`、`src/avatars/base.py:483-618`）：`render()` 以 try/finally 保證設 quit event；`process_frames` 出錯時結束說話狀態。
- `src/server/routes/chat.py:32-38`：非角色 echo 路徑使用未定義的 `started` → 已唸出卻回報失敗，重試唸兩次。修正回應。
- 守門：加入 pyright（dev 依賴、固定版本），對 `src/server` 只開 `reportPossiblyUnbound`（及 pyright basic 中可零誤報通過者），加進 CI。

完成：斷線不阻塞其他請求、echo 回傳成功的回歸測試；pyright 對 chat.py 舊碼報錯、修正後綠；完整 CI 通過。

## Comments
