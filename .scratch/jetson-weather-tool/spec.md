<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# Jetson Orin 單角色中央氣象署（CWA）氣候查詢整合規格

Status: resolved

更新日期：2026-11-03。透過 `/grill-with-docs`（`grilling` ＋ `domain-modeling`）完成兩輪設計樹訪談（Q1–Q8 全部確認），並於 `jetson-orin` 分支完成實作與驗證。

## 已確認設計決策（Q1–Q8）

### 1. 觸發與地點／日期解析（Q1、Q5）
- **兩階段輕量閘門**：
  1. **非天氣快速放行（0 ms）**：發話不含天氣／氣象／溫度／降雨／天氣生活建議詞彙，且本場對話無待續天氣追問時，直接進入原有回答流程，不發起任何額外 LLM 路由請求。
  2. **純規則快速路徑（< 1 ms）**：明確單一臺灣縣市（或未提地點但已有本場已確認地點／場域預設地點）＋天氣詞彙＋可解析相對或絕對日期，直接產出 `WeatherQuery`。
  3. **條件式結構化解析**：僅在具天氣線索或天氣追問上下文、但規則無法單獨拆解時，呼叫本機 `llama-server`（`json_schema`）抽取查詢欄位。
- **地點澄清與繼承規則**：
  - 單一臺灣縣市即足夠查詢（不強制要求鄉鎮，禁止模型猜測未明示鄉鎮）。
  - 缺少縣市（且無前文確認地點與場域預設地點）、地名歧義（如僅說「中正區」）或同句詢問多個縣市時，不查 CWA 也不多跑回答 LLM，直接依該場對話的**舞台語系**口述固定澄清提示並提交對話記憶：
    - `zh-TW`：`請問您想查詢臺灣哪個縣市的天氣？`
    - `en-US`：`Which city or county in Taiwan would you like the weather for?`
  - 當追問切換至新縣市時，自動清空上一輪的舊鄉鎮。

### 2. 回答生成、防幻覺與跨工具協作（Q2、Q6、Q7）
- **回答與看板生成**：將 `weather_prompt(result)` 注入本輪 `rag_context`，交由現有 LLM 依助手身分（`assistant_profile`）、可編輯回覆規則（`reply_rules`）及舞台語系（`zh-TW` / `en-US`）產出 `[[SPEECH]]` 口語摘要與 `[[BOARD_JSON]]` 看板項目。
- **防幻覺契約**：
  - 嚴格區分「未提供（`null`，如一週預報第 4–7 天無降雨機率）」與數值 `0%`。
  - 當 CWA 回傳 `missing_key`、`timeout`、`unauthorized`、`rate_limited`、`stale`、`out_of_range`、`not_found` 或 `unavailable` 時，透過 `weather_prompt(result)` 強制模型如實說明無法取得最新氣象資料或超出 7 天預報範圍，嚴禁以模型記憶猜測數值。
  - 當氣候工具關閉（`weather.enabled = false`）或未配置金鑰卻被問及天氣時，注入 `本輪未取得即時氣象資料，不可提供實際即時天氣數值。` 防止模型編造即時氣溫。
- **與 RAGFlow 及對話附件協作**：
  - **單純天氣提問**（無跨主題且未勾選本輪參考附件）：略過本輪 RAGFlow 檢索，省下 Orin 上 BGE-M3 嵌入延遲。
  - **複合問題或有勾選本輪參考附件**：保留附件解析與 RAGFlow 檢索，與 CWA 查詢非同步並行，再合併注入 `rag_context`。
- **可觀測性事件**：查詢完成時透過會話事件通道發送 `weather_lookup` 事件（含 `turn_id`、`status`、`county`、`town`、`kind`、`cached`、`query_seconds`）。

### 3. 設定層次、金鑰管理與控制台介面（Q3、Q8）
- **機密金鑰**：僅由環境變數 `NOVA_CWA_API_KEY` / `CWA_API_KEY` 或 `config/cwa.env`（列入 `.gitignore`）讀取，新增 `config/cwa.env.example`；API 只回傳 `configured: bool`，不暴露明文金鑰。
- **設定持久化**：
  - `Config` 新增 `WeatherConfig(enabled: bool = True, county: str = "", town: str = "")`，支援 `runtime_overrides.yaml` 讀寫。
  - 出廠預設：`config/config_jetson.yaml` 與 `config/config.yaml` 設為 `enabled: true`；`config/config_jetson_read_aloud.yaml` 與 `config/config_jetson_realtime.yaml` 設為 `enabled: false`。
- **控制台卡片（`WeatherSettings.vue`）**：置於 `SettingsPanel.vue` 的「知識庫檢索（`rag`）」分頁，提供：
  - CWA 金鑰狀態徽章與設定路徑說明。
  - 啟用開關、場域預設縣市（臺灣 22 縣市選單＋不指定）與場域預設鄉鎮市區輸入。
  - 即時測試查詢區塊（輸入測試問題，檢視解析出的地點／時段與 CWA 回應摘要）。

### 4. 會話隔離、呈現方式與快取邊界（Q4）
- **呈現方式無關**：MuseTalk 即時嘴型與預錄呈現共用同一套氣候查詢、語音與看板流程；`--read-aloud` 純朗讀不觸發氣候查詢。
- **會話隔離**：控制台對話與舞台對話各自獨立保存本場已確認的臨時查詢地點；執行「清空歷史」或觸發舞台「場次完整清空／閒置重置」時一併清除該會話臨時地點，回到**場域預設地點**。
- **共用快取**：後端單例 `CwaWeather` 維護 128 筆有界 LRU 快取（觀測 TTL 5 分鐘／觀測年齡上限 30 分鐘；預報 TTL 10 分鐘／發布年齡上限 8 小時），跨會話共用。

## 領域模型與文件紀錄

- [CONTEXT.md](../../CONTEXT.md)：已新增 **場域預設地點**。
- [ADR 0019](../../docs/adr/0019-single-role-weather-tool-on-jetson.md)：已記錄單角色氣候工具與兩階段輕量閘門決策。
