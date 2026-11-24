<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 訓練工作台介面
Status: ready-for-agent
Blocked by: 05, 06

依[規格](../spec.md)與 07 確認後的原型。在控制台實作訓練工作台，串接 05、06 的路由；補齊三份 locales；前端測試 0 失敗、0 跳過；`npm run lint`、`npm run build` 通過。不得為了介面方便而放寬任何路由的權限分類。

## 已確認的設計決定（2026-11-24）

依 `prototype/design.md`，管理者確認了規格第 12–17 點：入口在設定新分類「聲線訓練」；Edge 條文在選來源時確認；內建句庫免校對；第一版沒有下載路由；少量語料只提醒；舞台連線只顯示原因；完成畫面只有三句預設試聽。原型中的 50 MB、40 字、40–60 分鐘為示意值，以工單 05、06 的實際值為準。

## Comments

### 2026-11-24 實作摘要（分支 `mv2/08-training-ui`）

只動 `web/`（沒有改任何 Python、`tools/`、`scripts/`、路由權限）；沒有啟動應用伺服器、不碰 GPU。設定新增分類「聲線訓練」（`railTab-voiceTraining`，排在「數位人與畫質」之後，第一次點開才載入；該頁沒有頁面儲存列）。

**程式位置**
- 邏輯（純函式與 store，都有測試）：`web/src/voiceTraining/`：`api.js`（用可注入的 fetch；沒有任何下載或匯出的呼叫）、`textPreviewClient.js`（工單 13 的唯一呼叫點，回應形狀改了只改這一檔）、`reviewTable.js`、`preflight.js`、`jobView.js`（階段列、日誌 offset 合併、朗讀公告、自動逐字稿的 device 與退回原因）、`flow.js`（步驟、使用限制標示推導、各個「下一步」的條件、檔案預檢）、`store.js`、`constants.js`、`useText.js`。
- 畫面：`web/src/components/voice-training/`：`VoiceTrainingWorkbench.vue`（外框、步驟列、公告區、輪詢、樣式）、`VtHome`、`VtSource`、`VtEdgeConfirm`、`VtUpload`、`VtText`、`VtReview`、`VtEdgeTextReview`、`VtPreflight`、`VtJob`、`VtDone`，以及 `VtActionButton`（停用的按鈕用 `aria-disabled` 加 `aria-describedby` 連到原因）、`VtUsageBadge`（使用限制標示一律英文原文加圖示）。
- 語系：`settings.voiceTraining.*`，zh-TW、zh-CN、en-US 鍵與佔位符一致（測試守住，並檢查畫面用到的每個鍵都存在）。

**完成的畫面**：首頁（進行中的工作橫幅、語料清單、聲線模型清單）→ 語料來源（Edge 聲音下拉與份量／上傳）→ Edge 確認（條文引文、必須勾選、經伺服器記錄）→ 上傳錄音（三選一宣告與聲明、檔案清單與拒絕原因）→ 逐字稿（上傳 `.txt`／`metadata.csv`，或自動產生並顯示 device 與退回原因、CPU 預估）／朗讀文字（內建句庫，或上傳文字檔）→ 校對表（試聽、編輯、排除、確認、全部確認、數字展開預覽、無法處理的標記；Edge 上傳文字檔在合成前用 `text-preview` 校對，可改寫或移除，第 N 句）→ 訓練前檢查（伺服器每一項檢查與原因，顯存量表，開始鈕停用並列出所有原因）→ 訓練進度（階段、`role="log"` 日誌 offset 輪詢、先確認才取消，Esc 等同繼續訓練）→ 完成（標示、三句預設試聽、無下載）→「到數位人設定檔選用」（跳到設定檔分頁）。

**用到的 API**：`GET/POST /api/tts/corpora`、`GET /api/tts/corpora/{slug}`、`POST .../lines`、`PUT .../lines/{id}`、`GET .../lines/{id}/audio`、`POST .../transcripts`、`POST .../confirm`、`POST/GET/DELETE .../transcription`、`GET /api/tts/training`、`POST .../start`、`POST .../cancel`、`GET .../log?offset=`、`POST /api/tts/training/text-preview`、`POST /api/speech/preview`（完成畫面試聽）、`GET /api/speech`（訓練完成後重載聲線模型清單）。

**伺服器契約的缺口（介面已盡量優雅降級，需要伺服器補）**
1. **沒有建立 Edge 語料與記錄 Edge 條文確認的路由。** `POST /api/tts/corpora` 對 `edge-test-teacher` 回 409，`record_acknowledgement` 沒有任何路由呼叫。介面假設 `POST /api/tts/corpora {slug, source:"edge-test-teacher"}` 與 `POST /api/tts/corpora/{slug}/acknowledgement {shown_text}`（條文原文，須與 `MSA_CLAUSE.text` 逐字相同），都集中在 `api.js` 的 `createCorpus`／`recordAcknowledgement`。在伺服器補上之前，Edge 路徑在確認條文那一步會顯示伺服器的錯誤並停住。**阻擋 Edge 路徑完整走通，工單 10 前必須補。**
2. **試聽只有一句。** `/api/speech/preview` 固定念 `PROFILE_PREVIEW_TEXT`，不收句子；所以三句預設只有第一句（中文）可播，另兩句（含數字的中文、英文）按鈕 `aria-disabled` 並說明原因。伺服器若接受句子，只要把 `store.js` 的 `SERVER_SPEAKS_ONLY` 擴充。
3. **來源宣告沒有備註欄。** 原型的「授權文件備註」沒有對應欄位，介面略過，沒有假裝記錄。
4. **校對編輯沒有即時預覽。** 數字展開預覽在儲存後才更新（`PUT` 回傳的 `normalized_text`／`unresolved`）；沒有「只算不存」的路由，也不在前端複製一份數字展開。Edge 文字清單則在每次改寫後呼叫 `text-preview`。
5. **「還原」未做。** 伺服器不保留原始自動逐字稿，介面沒有「已修改／還原」。
6. **內建句庫的「查看句子範例」未做**（沒有取得句庫內容的路由）。
7. 檢查項目名稱與狀態文字依三語系翻譯，但伺服器的 `reason` 與 `message` 只有繁體中文，在 zh-CN／en-US 仍以中文顯示。
8. 校對表不知道每句長度（05 的已知限制），所以沒有「長度不在 0.5–15 秒」的提醒；品質檢查仍會在訓練工作中剔除。
9. 上傳檔案大小上限依 05 的實際值 20 MB，只在用戶端先擋，伺服器再檢查。

**驗證（Node 22）**：基準（`matcha-training` tip）`npm run lint` 通過、`CI=1 npm test` 272 通過、0 失敗、0 跳過，`npm run build` 通過；本分支 lint 通過、348 通過（新增 76）、0 失敗、0 跳過，build 通過。`console-visual`（真 Chrome，淺色與深色、1920×1080 與 1280×720）與 `settings-layout` 新增「聲線訓練」首頁、來源、Edge 確認、訓練前檢查四個狀態：文字對比至少 4.5:1、頁面不橫向捲動、卡片在格內捲動，通過。`scripts/check-integration.py` 通過（以主專案直譯器只讀取執行）。沒有改 Python，所以略過其他 Python 步驟。
