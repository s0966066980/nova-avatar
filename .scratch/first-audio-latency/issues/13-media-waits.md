<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 片段與渲染路徑的等待
Status: ready-for-agent
Blocked by: 01, 02

依[規格](../spec.md)。片段到 WebRTC 送出 P50 0.62 s：

- MuseTalk 待機時 sleep 約 160–190 ms（`src/avatars/musetalk/avatar.py:669`），開口時無法立即喚醒；未滿批次最多保留 0.35 s。改為有回覆音訊時立即喚醒、第一批不等滿批。
- 每輪與打斷後固定等待 0.3 s：確認是否在首音路徑上，在則移除。
- 以 issue 01 工具量測每項改動的效果，未改善者撤回。

## Comments
