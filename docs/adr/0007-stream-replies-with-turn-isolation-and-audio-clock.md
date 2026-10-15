---
status: accepted
---

# 以輪次隔離與音訊主時鐘串流數位人回覆

數位人回覆採伺服器擁有的可靠串流管線：LLM token 經語意切片進入有界 TTS channel，音訊 chunk 再驅動 MuseTalk 與 WebRTC；每個跨層資料都以 `turn_id`、generation 與 sequence 執行輪次隔離。取消後只提交已播回覆，未播放的文字、音訊與影格一律丟棄；媒體以音訊為主時鐘，嘴型落後時允許丟幀或重複，不得以排隊延遲語音。

## Considered Options

- 保留目前僅清空佇列的盡力取消：拒絕，因 executor 內的舊 LLM 串流可以在清空後重新產生舊輪次資料。
- 以視訊為主時鐘或保留全部嘴型影格：拒絕，因 MuseTalk 推理抖動會累積為語音延遲並破壞插話目標。
- 在使用者尚未說完時提前回覆：不在本決策範圍；系統仍於完整使用者發話完成後才開始模型回覆。

## Consequences

- LLM history 必須延後到輪次結束，並只提交實際播放的助手內容。
- TTS、MuseTalk 與 WebRTC 邊界必須接受並驗證同一份輪次 envelope，不能把 `turn_id` 當成純 metadata。
- 第一階段只保證 Edge TTS＋MuseTalk 的單一活躍會話；其他引擎維持相容但不承諾相同串流 SLO。
- 新管線以功能旗標漸進啟用，達成自動回歸與真實 soak 門檻後才成為預設。

## Implementation Status — 2026-09-01

- Edge TTS＋MuseTalk 的單一會話可靠串流管線已實作：語意切片、有界背壓、generation fence、播放提交、字幕／history、錯誤恢復與分階段指標均已接入。
- 50 回合真實 WebRTC soak 已達成首音、插話、恢復、A/V、媒體債務與 stale-output SLO；正式報告為 `.scratch/reply-voice-streaming/real-soak-mouth-continuity-50-rerun.json`。
- `reply_streaming.enabled` 仍預設關閉，因其他 TTS／Avatar 組合尚未取得同等 SLO；legacy 路徑保留為明確回退。
- direct PCM／decoupled audio clock 實驗路徑未通過聽感與 A/V gate，預設關閉。正式路徑維持單一 renderer-owned audio producer。
- MuseTalk 段落交界的視覺落差由嘴型連續控制器處理；控制器位於音訊 enqueue 之後，只改嘴部 ROI，不改變本 ADR 的音訊主時鐘。
- Edge TTS 無首包且重試耗盡時，失敗 envelope 會切回會話 event loop 立即終止輪次，只提交已播回覆；不得留下等待 watchdog 的未結束片段。
- Edge TTS 在服務 ready 前先完成一次無播放預熱；首包與續包使用不同逾時，避免程序冷連線落到第一輪，也避免首包短逾時截斷進行中的串流。
- Edge 使用長生命週期本機 event loop，並在第一個可播回覆片段開始出聲後最多預取下一段；這不是持久的遠端連線，播放順序與插話丟棄契約不變。
- MuseTalk 等待不足 PCM 的時間限制為 200ms；遠端 TTS 長尾期間必須持續推進待機影格，不能凍結上一張說話嘴型。

## Jetson Implementation Status — 2026-10-15

Edge TTS 啟動預熱與正式合成改為共用後端持有的長生命週期 event loop 與
WebSocket 連線池，取代上面 2026-09-01 記錄的每次重新建連方式。預熱須
完整消費該次合成並確認能解碼 PCM，才將連線留給第一輪回答；只執行獨立
腳本或在首個音訊封包後關閉串流，無法把可用連線交給正式合成。

閒置更新只建立連線，失敗採退避並尊重 Retry-After，避免定時合成增加
服務請求。共用範圍限於傳輸資源；輪次隔離、音訊主時鐘、播放提交與
插話丟棄規則沿用原契約。中途取消或失敗的連線不回池，會話斷線不停止
其他會話的傳輸，後端關閉時清理共用連線池。
