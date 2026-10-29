<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 反向角色交接驗證

日期：2026-10-29。使用者已確認 Q1–Q3、完整規格並要求開始實作。

## 回歸與實際模型

新增測試先確認舊版沒有反向交接、地點驗證誤擋非天氣問題及沒有返回
文案遷移。另以先失敗後修正的案例鎖定兩個附件驗證競態：新問題不能
被晚到的舊接續取代，舊接續失敗也不能取消新一輪的正向交接。

聚焦驗證：

```bash
uv run pytest tests/test_reverse_role_handoff.py tests/test_role_coordinator.py tests/test_avatar_profiles.py tests/test_pc_conversations.py tests/test_conversation_attachments.py -q
```

101 passed。涵蓋中英文、控制台／舞台、文字及 ASR 後的共用生成入口、
播放完成與轉場柵欄、一次交付、角色身分／記憶隔離、再次正向交接、
取消／播放失敗／目的角色失敗、混合主題、附件能力與過期接續隔離。
前端實際元件測試驗證有標籤的兩個返回文案欄位及儲存／套用。

```bash
uv run python .scratch/reverse-role-handoff/validation/probe_routing.py
```

以目前保存的 `Qwen3.5-9B-UD-Q4_K_XL` 在 RTX 4090、獨立 18080 埠
執行 14 個合成問題，14/14 符合預期。包含服務介紹、超出主角色知識的
問題、多縣市的一般問題、天氣、爬山建議、週末追問、混合主題與選定
優先主題、中英文及既有正向交接。只讀取現有設定，結束後停止本次
持有的 llama-server；沒有修改正在使用的設定或啟動完整後端。
逐案結果見 [routing-results.json](routing-results.json)。

## 完整驗證

- `uv run ruff check .`：通過。
- `uv run python scripts/check-integration.py`：通過，含品牌與授權契約。
- `uv run pytest`：787 passed、3 skipped，88.00 秒。
- `web/` 的 `npm run lint`、`npm test`、`npm run build`：通過，159 個
  Web 測試成功。正式建置保留既有空 bootstrap chunk 與大型 bundle 提醒。
- `git diff --check`：通過；新檔保留 Nova Avatar Apache-2.0 notices，
  繼承的 voice session 原有上游與修改 notices 均保留。

## 現場驗證邊界

上述語意測試使用真實模型；回歸中的 LLM 回答、音畫輸出與播放確認
使用測試替身，因此不代表真人麥克風／喇叭、瀏覽器實際觀看或 MuseTalk
轉場畫面已通過現場驗收。完整 WebRTC／實體音畫驗收仍須另行執行。
