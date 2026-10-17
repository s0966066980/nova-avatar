<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright 2026 HongXian0903 -->

# 免費即時天氣 API 查證

查證日期：2026-10-16（Asia/Taipei）。本文件比較官方資料與條款，並彙整主工作提供的匿名 HTTP 測試；尚未選定正式供應商、註冊帳號或申請金鑰。搜尋工具顯示的「today／last month／3 months ago」是其回傳抓取標籤，不等同於本次條款的生效日期。

決策更新：研究完成後，使用者於第三輪確認首版採 CWA、僅支援臺灣；以下候選比較保留研究當時的內容，已確認需求與剩餘問題以[訪談紀錄](map.md)及[功能規格](spec.md)為準。尚未使用授權碼完成 CWA 有效查詢測試。

補充查證：官方[鄉鎮產品說明](https://opendata.cwa.gov.tw/opendatadoc/Forecast/F-D0047-001_093.pdf)明列一週預報的降雨機率僅前三天提供，第 4–7 天須標示未提供；三天與一週產品的機率區間不同。匿名唯讀取得[官方 Swagger](https://opendata.cwa.gov.tw/apidoc/v1)已確認各縣市直接端點及 `F-D0047-093` 選集參數，但尚未以金鑰驗證混合產品 JSON。完整回傳驗證與資料時間映射列入規格驗收。

## 適合本案的方向

**建議臺灣服務先評估中央氣象署（CWA），國際免費商用候選評估 WeatherAPI.com；Open-Meteo 適合免金鑰驗證與符合條款的非商業用途。** 此為依本案臺灣數位人問答需求作出的研究建議，尚未成為專案決策。天氣角色應透過即時查詢工具取得資料；Prompt／RAG 可保存解說知識，不能自行生成今天或明天的天氣數值。

「即時」在此應指查詢當下可取得的最新資料。觀測站測量、模式估計的現在天氣、未來預報是不同產品；15 分鐘時間格點不代表每 15 分鐘重新觀測或產製。回答需帶有地點、資料來源、資料時間或預報有效區間，不能承諾逐秒更新。

## 候選比較

| 候選 | 免費與金鑰 | 免費商用／展示 | 現在天氣與免費預報 | 主要條件 |
| --- | --- | --- | --- | --- |
| CWA 開放資料 | 指定觀測／預報資料集標示免費；免費會員取得授權碼 | 所引資料集採政府資料開放授權條款第 1 版，可作商業利用並須顯名 | 測站觀測另取觀測集；鄉鎮預報可涵蓋未來 3 天與 1 週 | 固定呼叫額度未由本次官方頁面確認；需正確挑選鄉鎮資料集 |
| WeatherAPI.com | 免費 100,000 次／月；需 key；官方明示免信用卡 | 官方明示 Free 允許商用；須標示名稱或 Logo | 全球現在天氣、3 天每日／每小時預報 | 免費方案不能因此推定有政府警報；單一 key／訂閱限一個應用或服務 |
| Open-Meteo | 免費端點免 key；不需付費註冊流程 | 免費託管 API 僅非商業；商用需付費訂閱 | 全球模式現在值；預報預設 7 天、最多 16 天 | 少於 600 次／分、5,000 次／時、10,000 次／日；定價表另列 300,000 次／月 |
| OpenWeather Free | 需 key；60 次／分、1,000,000 次／月 | 官方自助方案允許商用，ODbL 與可見顯名 | 全球現在天氣、5 天每 3 小時預報 | Free 詳表列天氣資料每 2 小時更新；One Call 為另一項計費訂閱 |

上表來源分別為 [CWA 使用說明](https://opendata.cwa.gov.tw/devManual/description)、[CWA 觀測資料政府目錄](https://data.gov.tw/dataset/9178)、[CWA 預報產品說明](https://opendata.cwa.gov.tw/opendatadoc/Forecast/F-D0047-001_093.pdf)、[WeatherAPI 首頁](https://www.weatherapi.com/)、[WeatherAPI 定價](https://www.weatherapi.com/pricing.aspx)、[WeatherAPI 條款](https://www.weatherapi.com/terms.aspx)、[Open-Meteo 使用條款](https://open-meteo.com/en/terms)、[Open-Meteo 定價](https://open-meteo.com/en/pricing)、[Open-Meteo API 文件](https://open-meteo.com/en/docs)、[OpenWeather 定價](https://openweathermap.org/price)、[OpenWeather 詳細方案與授權](https://openweathermap.org/full-price)。

## CWA：臺灣優先候選

- 帳號：有效電子郵件可免費申請會員；API 需有效會員授權碼，可放在 HTTP `Authorization` header。文件沒有要求信用卡；本次未實際註冊驗證。[官方使用說明](https://opendata.cwa.gov.tw/devManual/description)
- 觀測：`O-A0003-001` 是測站 10 分鐘綜觀資料，政府目錄標示每 10 分更新、免費、政府資料開放授權條款第 1 版。測站數值不是任意地址的直接測量，須保留站名／測量時間。[官方政府資料目錄](https://data.gov.tw/dataset/9178)
- 預報：官方產品涵蓋全臺 368 鄉鎮，公所為代表點；未來 3 天有逐 3 小時資料，未來 7 天有逐 12 小時及逐日資料。每日 05:30、11:30、17:30、23:30 發布，必要時可能另外更新；繁中文案包括天氣現象與綜合描述。代表點不能保證描述同鄉鎮所有山區／海拔條件。[官方產品 PDF](https://opendata.cwa.gov.tw/opendatadoc/Forecast/F-D0047-001_093.pdf)
- 選集：`F-D0047-091` 的政府目錄名稱含「鄉鎮」，但產品格式允許 Location 是「鄉鎮或縣市」，不能據名稱保證回傳所有鄉鎮；全臺 3 天集 `F-D0047-089` 頁面亦可見縣市代表點。實作時應選各縣市鄉鎮系列，或核對 `F-D0047-093` 的 `locationId`／`locationName` 篩選及實際回傳粒度。[091 政府目錄](https://data.gov.tw/dataset/9308)、[089 官方資料頁](https://opendata.cwa.gov.tw/dataset/all/F-D0047-089)、[官方 API 篩選範例](https://opendata.cwa.gov.tw/opendatadoc/CWA_Opendata_API_V1.3.pdf)
- 授權：所引資料集採政府資料開放授權條款第 1 版，涵蓋商業利用、公開傳輸與衍生利用，須依附件顯名，不含商標權。建議舞台標示「資料來源：交通部中央氣象署」並提供資料集／授權連結；具體顯名須對照選定資料集聲明。[官方授權條款](https://data.gov.tw/license)
- 額度：本次可讀的官方使用說明、資料目錄未找到目前固定每分鐘／每日呼叫上限，**未確認，不能寫成無限**。有 ETag／If-None-Match 快取指引；定案前核對帳號與當時平臺規範。部分 CWA 網頁由 JavaScript 載入，瀏覽工具只取得提示，因此以政府資料目錄及官方產品 PDF 交叉查證。

## WeatherAPI.com：免費商用全球候選

- Free 方案為 100,000 次／月、免信用卡、允許商用，含現在天氣及 3 天每日／每小時預報；需註冊 key。全球覆蓋可用城市或經緯度查詢，但未找到承諾臺灣所有鄉鎮行政邊界／測站解析度的官方聲明。[官方首頁](https://www.weatherapi.com/)、[官方請求參數](https://www.weatherapi.com/docs/)
- 官方定價 FAQ 說現在天氣來自全球公共／私人站與資料供應商，每 10–15 分更新；預報由其預報系統產製，每 4–6 小時更新。不能推定任意座標的回傳值就是該座標有一支實體測站。[官方定價與 FAQ](https://www.weatherapi.com/pricing.aspx)
- `lang=zh_tw` 可翻譯 `condition.text`，其他欄位不變；不要承諾所有地名／警報皆翻成繁中。[官方多語文件](https://www.weatherapi.com/docs/multilingual/)
- Free 使用須顯示 WeatherAPI.com 名稱或 Logo；單一 key／訂閱限一個應用／服務，不得轉售天氣資料；現在值最多快取 60 分鐘、預報最多 24 小時。公開場域多裝置是否同一服務，仍應按實際部署解讀條款，必要時詢問業者。超過免費月額度會停止取得當月資料。[官方條款](https://www.weatherapi.com/terms.aspx)、[額度 FAQ](https://www.weatherapi.com/pricing.aspx)

## Open-Meteo：免金鑰驗證候選

- 免費託管 API 僅非商業。條款明列商業產品與促銷活動為商用；即使數位人舞台不向觀眾收費，仍不能據此當作非商業。商用須付費訂閱及 customer endpoint/key；資料 CC BY 4.0 允許商用，並不取消免費 API 的用途限制。[官方使用條款](https://open-meteo.com/en/terms)、[官方定價](https://open-meteo.com/en/pricing)
- 免費限制同時包含每分、每時、每日，定價表另列每月上限；多座標、長時段或變數多的請求可被計為多次，不能直接把每個 HTTP 請求都當一次。[官方定價與計次說明](https://open-meteo.com/en/pricing)
- `current` 明確是 15 分鐘天氣模式資料，臺灣不在原生 15 分鐘區域，其他區域可由逐時內插。預報預設 7 天、最多 16 天；模型更新頻率依來源不同。全球經緯度查詢包含臺灣，但沒有臺灣鄉鎮公所代表點語意；回傳 WMO 天氣代碼，繁中描述需應用映射。[官方 API 文件](https://open-meteo.com/en/docs)
- API 資料 CC BY 4.0，需適當顯名、連結授權、標示修改；官方要求在資料展示位置旁放 Open-Meteo 連結。託管 API 的使用與自行部署 AGPLv3 伺服器是不同事項。[官方授權](https://open-meteo.com/en/licence)

## OpenWeather：另一個全球候選

- **Free 與 One Call 分開看**：Free 含現在天氣、5 天逐 3 小時預報，60 次／分及 1,000,000 次／月；需 key。官方 freemium 指引是 email 註冊取得 key，未明確寫免信用卡，本次未註冊驗證，故信用卡需求記為未確認。[官方定價](https://openweathermap.org/price)、[官方啟用指引](https://openweathermap.org/appid)
- 詳細方案頁把 Free 天氣資料更新列為每 2 小時；一般 FAQ／API 指引另說模型每 10 分更新、建議單地點不要高於每 10 分查一次。這些不同層次的敘述不能當作 Free 保證 10 分刷新。本案若重視新鮮度，應依 Free 詳表保守評估，再測量時間戳。[官方詳表](https://openweathermap.org/full-price)、[官方使用建議](https://openweathermap.org/appid)
- 覆蓋全球座標，提供 `lang=zh_tw` 天氣描述。資料綜合測站、雷達、衛星與模型，不能一律稱作現場直接觀測；未找到官方臺灣每鄉鎮固定解析度承諾。[現在天氣文件](https://openweathermap.org/api/current)、[官方技術 FAQ](https://openweathermap.org/faq)
- 自助方案可商用，採 ODbL，需在使用處可見顯名；重新整併成向外提供的天氣資料庫可能適用相同方式分享。一般應用使用資料不要求公開其程式碼。FAQ 另列名稱、連結與 Logo，展示版宜採較完整顯名。[官方授權說明](https://openweathermap.org/full-price)、[官方顯名 FAQ](https://openweathermap.org/faq)
- 官網目前推 One Call **4.0**，3.0 標示 deprecated。One Call 是另訂閱的按次付費產品，每日前 1,000 次免費，超出會計費；不能把其免費額度誤作無帳務風險的永久 Free。預設每日限額為 2,000 次，高於免費部分。此次沒有申請或開通。[官方定價](https://openweathermap.org/price)、[官方 One Call FAQ](https://openweathermap.org/faq)

## 本次匿名連通測試

主工作於本次查證提供以下結果，原始紀錄保存在同目錄：

- [weather-api-smoke.json](weather-api-smoke.json)：Open-Meteo forecast 端點，使用臺北座標匿名 GET，HTTP 200；現在值時間間隔為 900 秒、時區 `Asia/Taipei`，168 個逐時點及 7 天逐日預報均非空，單次耗時 0.922 秒。這只證明該次連通性與回傳結構，沒有驗證準確率、資料新鮮度保證或服務 SLA。
- [weather-geocoding-smoke.json](weather-geocoding-smoke.json)：獨立 geocoding 端點搜尋 Taipei，單次 HTTP 502。未重試，不據一次結果推定長期可靠性；正式功能仍需地點查詢失敗／歧義處理。
- CWA、WeatherAPI.com、OpenWeather 需要授權碼的資料呼叫尚未完成有效金鑰端到端測試。

## 待使用者決定與後續驗收

1. 查詢地理範圍：先只做臺灣，或同版納入全球；選 CWA 為臺灣優先候選、是否另配全球候選。
2. 顯示需求：目前觀測、今天／明天／未來一週預報各要哪些欄位；若只問「這裡」，使用控制台設定場域地點；跨地區或歧義先澄清。
3. 部署用途：公開商業／品牌展示或符合非商業條款的測試；這會影響 Open-Meteo 免費端點是否適用。
4. 正式介接前取得使用者自行管理的 key，核對方案與配額；本研究不要求貼 key 到對話，也不探查現有 secrets。
5. 驗收應涵蓋問明天天氣、保留前文地點的「那明天呢」、同名地點、超出預報範圍、資料過舊／API 逾時、配額耗盡、切換／返回後舊查詢不漏到新輪次。失敗時明說暫時無法取得最新資料，不能用模型記憶代替。

目前沒有對不同供應商預報準確率作排名；推薦只依範圍、欄位、授權、更新頻率與接入條件。
