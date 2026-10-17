<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# CWA 即時觀測與預報
Status: resolved

依[完整規格](../spec.md)實作服務端授權碼、地點與日期、觀測／三天／一週解析、時間／區間／缺值、快取及逾時。以 fixtures 驗證，不以缺值或模型猜測補天氣；金鑰端到端測試另列實際結果。

## Comments

2026-10-16：CWA adapter、位置與日期、缺值／時間政策、快取、三秒總預算已實作。有效授權碼已實測目前觀測、明日及七天預報與快取；量測見 ../cwa-latency.json。授權碼未寫入測試結果。

2026-10-17：10 項 CWA 測試及完整回歸通過。以有效服務端授權碼重新查詢即時觀測、明日與七天預報，三種冷查詢均 available（約 53–101 ms），第二次均命中快取，見 [當日實測](../cwa-latency-2026-10-17.json)。401／429／逾時及缺值恢復由 fixtures 驗證；不將 fixtures 視為對官方服務的實際限流測試。
