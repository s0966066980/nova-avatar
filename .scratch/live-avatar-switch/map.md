<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->

# 兩位數位人即時切換：設計訪談

Status: resolved

## Notes

使用者明確要求：

- 在兩位數位人之間即時切換。
- 以設定檔保存每位數位人各自的 Prompt、RAG 與模型。
- 支援自行上傳轉場影片。
- 支援內建轉場特效，並可從控制台選擇效果。
- 使用 grill-with-docs 逐輪釐清需求，隨已確定的術語及取捨更新領域文件。

設計、實作與驗收已完成，包含角色設定檔、角色交接、CWA 與兩端介面；驗證結果另見下方實作進度與證據索引。

[功能規格](spec.md) 整理已確認契約與驗收情境；使用者已確認 Q23–Q27、
完整規格及開始實作。後續不再為這些決策重複請求確認。

## Decisions-so-far

2026-10-17 驗證收尾：

- [01 設定檔與記憶](issues/01-profiles-and-memory.md)、[03 CWA](issues/03-cwa-weather.md) 與 [04 兩端介面實作](issues/04-console-and-stage.md) 已完成各自自動驗證；完整 Python 581 passed／3 skipped，前端 100 passed 並完成 build。
- [02 交接與媒體](issues/02-handoff-and-media.md) 亦已完成：舞台／控制台各 50 輪，專門回答首音 p95 為 1.834／1.656 秒。控制台重跑另存新檔，保留原本 42 輪的紀錄。
- [05 整體驗收](issues/05-validation.md) 已完成自動／RTP 驗證、預載成本與資源量測，並依使用者指定以 Playwright 控制本機 Chrome 補完觀看端數位音訊／影格及互動驗收。完整證據索引見 [validation-results.json](validation-results.json) 與 [Chrome 驗收](chrome-acceptance.json)。

第一輪已確認（2026-10-16，使用者最終合併答覆 Q1–Q7）：

- 主數位人收到天氣問題時，先口述交接說明，再切換至天氣數位人；
  天氣數位人接續回答原問題，訪客不必重新提問。
- 這是主數位人至專門數位人的角色交接，不沿用先前「立即取消 A
  並切 B」的建議作為自動交接行為。說明須先實際播出，不能以模型
  生成完成或語音入列當作播放完畢。
- 只在專門數位人作用中顯示返回主數位人的按鈕，返回亦經轉場。
  第二輪已確認舞台與控制台都有按鈕，說話中按下立即停止剩餘回答。
- 每份設定檔保存人物素材、身分／限制 Prompt、LLM、RAG、聲音與
  回覆規則；共用 MuseTalk 推理引擎的建議已接受，舞台背景獨立共用。
  這不表示已實現兩個不同本機 LLM 同時駐留。
- 同一訪客各角色的記憶分開保留；切回角色接續其自己的記憶；訪客
  對話重置清除各角色記憶。第二輪已確認交接原問題與必要的已確認上下文。
- 控制台預覽與舞台使用同一個作用中角色；不由此推論兩者共用完整
  對話、音訊或看板。
- 可保存多份設定檔，再選兩份作為當次主／專門角色組合。
- 「紀錄」指保存上述目前設定，沒有要求設定版本歷程或還原。
- 內建特效作用於人物層；自訂影片覆蓋舞台。可指定來源角色與目的
  角色，再設定該方向使用影片或特效；A→B 與 B→A 各自設定，
  不把 A→B 影片自動倒播作為返回影片。

已寫入 [CONTEXT.md](../../CONTEXT.md) 與
[ADR-0016](../../docs/adr/0016-isolate-avatar-profiles-and-visitor-memory.md)。
設定檔欄位的識別方式、遷移與執行時機仍在訪談範圍內。

第二輪已確認（2026-10-16，使用者「全部根據建議」並明確擴充即時天氣）：

- Q8：接手主題可設定，以天氣為第一個驗收案例，當次仍為主／專門兩位。
- Q9：主數位人的 LLM 依控制台的交接規則與專門角色介紹判斷；語意
  不明確時先詢問訪客。程式驗證目的角色必須是當次選定的專門角色。
- Q10：交接原問題及必要的已確認上下文，例如地點、日期；角色記憶
  各自保存，不把完整跨角色歷史當成共用對話。
- Q11：每個交接方向可編輯固定交接說明，先播完再轉場。
- Q12：舞台與控制台都有返回按鈕，僅在專門角色時顯示；人工返回時
  停止剩餘回答、只提交已播內容，再轉回主角色，保留兩角色訪客記憶。
- Q13：使用者明確要求本次包含即時天氣預報串接，取代前輪建議的
  另行立項。需研究免費且可取得最新天氣的 API，尚未選定供應者。
- Q14：閒置訪客對話重置時清兩角色記憶，並轉場回主數位人。

第三輪已確認（使用者針對 Q15–Q22 回覆「根據建議」）：

- Q15：首版採 CWA 並支援臺灣；全球供應者之後加入。
- Q16：控制台設定場域預設縣市／鄉鎮，未指定時使用且在回答中說明
  地點；訪客臨時地點只保留於本訪客對話。
- Q17：專門角色收到非專長問題時維持角色並提示可返回；混合主題
  先詢問優先主題，不自動反向交接。
- Q18：目標角色就緒才播交接說明；說明中可插話取消，轉場期間
  暫停收音及重複切換。準備失敗留主角色；API 失敗明說查不到最新資料。
- Q19：內建淡入淡出、左右滑動、縮放；自訂影片首版採靜音。
- Q20：同一人物素材可建立多份角色設定檔；既有有效設定先建立成
  主角色設定檔。
- Q21：開始轉場清除舞台字幕與看板，返回不重顯示舊答案；控制台
  保留各角色紀錄供查看，角色記憶仍依原決策保留。
- Q22：`musetalk_angela` 主角色、`musetalk_1` 天氣角色，共用目前
  `Qwen3.5-9B-UD-Q4_K_XL`，各自套用角色設定；實作後量測雙素材
  預載及切換延遲，尚無新的雙角色實測成績。

即時天氣 API 研究已完成，詳見
[weather-api-research.md](weather-api-research.md)：

- 建議臺灣優先評估 CWA，全球免費商用評估 WeatherAPI.com；
  Open-Meteo 適合免金鑰且符合非商業條款的驗證。使用者已於第三輪
  確認首版採 CWA；其他候選保留為研究資料。
- CWA 提供分開的測站觀測與預報產品；所查觀測集每 10 分更新，
  鄉鎮預報每日四次。固定 API 呼叫上限本次未確認，不視為無限。
- Open-Meteo 臺北預報匿名 GET 成功，取得目前值及七天預報；
  獨立地名查詢單次 HTTP 502。只做連通與資料結構驗證，未做準確率
  或服務可用率評估。原始結果連結位於研究文件。
- 其他需授權碼的候選尚未做有效金鑰呼叫；未註冊或申請任何帳號。

本機素材／模型補充查證：

- 現有 MuseTalk 素材為 `musetalk_angela`、`musetalk_1`，皆有綠幕
  與預覽，使用者第三輪已確認其分別為主角色與專門角色。
  兩者原圖分別為 720×1280、1080×1920，須驗收共同舞台輸出規格
  下的縮放及構圖，不能因 catalogue 可列出便視為已通過切換驗收。
- 有效 runtime 選擇為 `musetalk_angela`、llamacpp 的
  `Qwen3.5-9B-UD-Q4_K_XL`、Edge `zh-TW-HsiaoChenNeural`。
  共用同一個 LLM 與同一個 MuseTalk 推理模型，已選為首版驗收策略；
  尚未量測兩份人物素材預載的額外成本。
- 另有 Wav2Lip 素材，仍屬 Research / Non-commercial，並未作為本案
  一般部署的優先候選。本次僅唯讀查證，未啟動或切換任何服務。

已查證的現況（main 工作區及 origin/jetson-orin@46db729）：

- `src/server/runtime_settings.py:apply_avatar()` 在仍有 WebRTC 會話時回
  409，現有角色切換需要先斷線。
- Prompt／助手身分、LLM、TTS 與回覆規則目前共用；RAG 啟用狀態及
  dataset 已依 `avatar_id` 保存。對話記憶依會話保存，沒有角色持久記憶。
- `AvatarTransitionController` 處理單一角色說話至待機的銜接；Orin 的
  預錄呈現處理同角色 idle/talking 素材。兩者都不是 A/B 角色切換轉場。
- 同 MuseTalk 引擎可重用模型，但目前沒有兩位角色的預載池。
- `src/llm/llamacpp.py:ensure_server()` 只管理一個本機 LLM；選另一個
  GGUF 時會停止原程序。尚無兩個不同本機 LLM 的駐留量測。
- 既有 x86 報告只證實一組 MuseTalk、TensorRT 與 Qwen3.5 9B 共跑，
  無法用來承諾雙角色／雙 LLM 的記憶體用量與切換時間。

第二輪補充查證（唯讀，未修改應用程式）：

- `src/llm/prompts.py:AUTO_MODE_PROMPT`、
  `response_protocol.py:ResponseProtocolParser` 只支援 SIMPLE／BOARD
  及口語／看板分流，`rules.py:RULE_FIELDS` 沒有交接規則。
  `OpenAILLM.chat_stream()` 未執行工具呼叫，現有 `ReplyRouter` 也只
  選回答呈現模式。需要新增明確交接控制，不能把角色 JSON 當語音。
- `VoiceTurnSession.on_output_audio_frame()` 能標記有效片段最後幀；
  `_all_registered_fragments_ended()` 等待生成完成及所有片段結束。
  這是伺服器交付 WebRTC sender 的邊界，沒有觀看端已聽完的 ACK。
  `assistant_response_done` 只是模型生成完成，不可用它開始轉場。
- `_process_turn()` 與文字輸入路徑都持有原問題；已提交 history 僅有
  已播回覆，已確認顯示的看板另外保存。沒有現成跨角色交接封包。
- `web/stage.html:send()` 已能透過 ordered `voice-events` DataChannel
  回傳控制；`VoiceTurnSession.handle_control()` 目前只有 capture、
  interrupt、board_displayed，尚無返回主角色指令。
- 控制台與舞台各有隨機 sessionid、LLM instance 與看板，不共用訪客
  對話。`_schedule_idle_reset()` 只作用於舞台會話；
  `reset_conversation()` 清該會話內容而不切角色。沒有共同訪客識別。

第三輪答覆後補充查證：

- 目前沒有全域主輸入來源或跨頁輪次互斥；舞台連線／回答中不會
  阻擋控制台獨立語音、文字或測試。各 VoiceTurnSession 只管理自己，
  需要 Q23 決定共用角色下的輸入協調。
- Profile 修改現在會清全服務 history，但不取消正在產生的舊回覆；
  Rules／RAG 為下一輪快照。新角色設定檔套用不能直接沿用目前的
  全域更新／清除方式，需按設定檔及輪次隔離。
- 現有背景影片上傳限制 100 MiB、首幀可解碼及總像素上限，沒有
  影片時長或完整 codec／fps／音軌正規化；不能直接當作新轉場影片契約。
  服務端 VideoTrack 固定 25 fps，輸出尺寸仍依角色原幀及高度限制。
- CWA 官方一週產品的降雨機率僅前三天提供；時間區間及來源缺值
  必須保留。Swagger 已查到各縣市三天／一週直接端點及093選集參數，
  但有效金鑰的實際 JSON shape 尚未驗證，見規格與研究紀錄。

涉及的既有決策：

- [ADR-0012](../../docs/adr/0012-editable-rules-for-single-llm.md)：目前回覆
  規則由服務共用；ADR-0016 已修訂設計範圍為每份設定檔各自保存，
  原先固定協定及自然語言規則的原則保留。
- [ADR-0013](../../docs/adr/0013-use-ragflow-for-retrieval-only.md)：每角色
  知識範圍隔離；切換後不得沿用舊角色未完成的檢索結果。
- [ADR-0014](../../docs/adr/0014-compose-green-screen-avatars-on-server.md)：
  曾將預載、保持 WebRTC track 與人物層淡接列為後續工作。
- [ADR-0015](../../docs/adr/0015-console-owned-assistant-profile.md)：身分
  變更時清除歷史與看板。ADR-0016 區分選擇既有設定檔與修改身分，
  選擇角色本身保留本訪客各角色記憶。

## 實作與驗收進度（更新至 2026-10-17）

- 設定檔與一次性遷移、revision、每會話／角色記憶已實作。
- 單一輸入來源、交接音訊完成柵欄、定向媒體轉場、保持 track 的素材切換已實作。
- CWA 觀測／三天與一週預報 adapter、快取與時間政策已實作；有效授權碼已取得資料，見 `cwa-live-results.json`。
- 控制台角色設定、輸入模式、角色歷史與兩端返回操作已接線。
- 自動回歸完成：integration／rebranding audit、Python 581 passed／3 skipped、web 100 passed、build 及 diff whitespace 檢查皆通過。
- `role-soak-50.json` 保留原舞台 50 輪／控制台 42 輪；控制台另以 `role-soak-console-50.json` 完整重跑 50 輪。兩份完成的紀錄各含 100 次去／回程轉場。
- 雙端真實 WebRTC 補測通過取消、返回、輸入互斥、自訂靜音片／內建特效、記憶重置及 tracks 保持；觀測到的伺服器 A/V 配對偏移約 21 ms，不能替代觀看端同步驗收。
- 雙素材預載的 RAM／GPU 增量及套用耗時已另行量測，見 `role-preload-cost.json`；長測資源峰值見各 resources 檔。
- 原瀏覽器工具不可用後，使用者明確指定 Playwright；已完成本機有視窗 Chrome 155 的控制台與舞台驗收。過程修正示例字幕、空看板按鈕與影片預先顯示首幀問題；最新完整回歸為 Python 582 passed／3 skipped、web 100 passed、build 及 integration audit 通過。

## 驗收待辦

第四輪已確認（Q23–Q27，完整方案詳見規格的同名表）：

23. 舞台與控制台的主輸入來源／測試模式、輸入切換時機。
24. 首版即時組合的共用模型限制、雙素材預載及切換首音驗收目標。
25. 天氣欄位、七天範圍與機率三天限制、快取及資料過舊政策。
26. 影片格式、大小、時長、正規化、共同輸出及內建特效時長。
27. 重啟回主角色、設定套用時機、各類修改的記憶失效及使用中刪除。

訪談已完成且使用者已確認共同理解，開始功能實作。
工程查證與驗收狀態：

- CWA 有效授權碼的觀測、明日與七天預報及快取已實測；401／429／逾時／取消恢復由 fixtures 驗證，並未對官方服務刻意觸發實際限流。
- 雙素材預載成本、720×1280 RTP 輸出、舞台／控制台各 50 輪 soak、完整 integration／rebranding audit、Python／web 測試及 build 已通過。
- 觀看端交接語音／轉場／回答的順序、嘴型動作及共同輸出構圖已由 Chrome 解碼媒體與截圖檢查；詳細方法與實體音響／麥克風未測的範圍界線見 `chrome-acceptance.json`。

主數位人、專門數位人、數位人設定檔、角色對話記憶、角色交接、交接
說明與角色轉場已收錄於領域詞彙；尚未確認的行為不寫成既定規格。
