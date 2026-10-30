<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 任意角色交接的執行期
Status: ready-for-agent
Blocked by: 01

依[規格](../spec.md)。`src/profiles/coordinator.py`、`src/server/voice_session.py` 改為任意來源→目的：交接說明取目的成員的那一句；轉場取個別覆寫否則預設；主數位人開場與兜底、「返回主數位人」與訪客對話重置回主數位人；閒置招呼只在主數位人；各角色對話記憶照舊隔離。

- 素材與資源：套用組合時處理所有啟用成員的人物素材；先查明多位成員的人物素材快取對記憶體／顯存的影響（現在只載兩位），在 Comments 回報並採用不讓顯存隨成員數暴增的方式（例如按需載入或共用快取），必要時列待實機驗證。
- 取代所有寫死兩角色的地方（清單見 role-pair-map.md）。

## Comments
