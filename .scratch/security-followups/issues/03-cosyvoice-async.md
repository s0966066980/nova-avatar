<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# CosyVoice 伺服器端點阻塞 event loop
Status: ready-for-agent

`scripts/cosyvoice_fastapi_server.py` 的 `async def` 端點仍在 event loop 上執行第一次推論與暫存檔清除（`_remove_temporaries()` 移到同步 helper 後 ruff 不再標記）。一次合成期間，同一伺服器的健康檢查與其他請求會停住。

改為 `def` 端點（FastAPI 交給執行緒池）或以 `asyncio.to_thread` 包住推論；須確認模型是否可並行推論，必要時以鎖序列化。完成：合成期間 `/health` 仍可回應的測試。

## Comments
