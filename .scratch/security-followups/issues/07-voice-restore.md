<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 參考音訊回收桶還原與刪除檢查
Status: ready-for-agent

`src/tts/voice_library.py` 刪除會移入 `.deleted`，但沒有還原端點與介面；刪除時也不檢查尚未套用的設定（`config/pending_settings.json`），那些設定要到套用時才驗證失敗。

比照數位人與背景的回收桶：列出、還原、永久刪除（管理類路由，加入 `ROUTE_ACCESS`）；刪除時一併檢查待套用設定。

## Comments
