# 場域試營運規格

Status: in-progress

## 情境

單一場域、一台主機。訪客在數位人舞台（`/stage.html`）直接說話，一次一位；現場人員只開關機，
管理者遠端或事先配置。詞彙見 `CONTEXT.md`（場域、訪客、現場人員、管理者、數位人舞台、控制台、
訪客對話重置）。

## 凍結的上線組合

Edge TTS ＋ MuseTalk ＋ FunASR ＋ llama.cpp（Qwen3.5-9B）＋ Silero VAD ＋ 串流回覆開啟，
即 `runtime_overrides.yaml` 的實際設定。其他數位人引擎、TTS、STT 不納入場域驗收。
場域接受雲端 Edge TTS；上線前必須實測 Edge TTS 能出聲。

## 本階段交付

1. Edge TTS 端點改用 `api.msedgeservices.com`，握手被拒時換主機（commit 620f8fc）。
2. 舞台只顯示簡短友善的錯誤提示，技術細節只寫瀏覽器主控台與後端日誌。
3. kiosk 模式：`scripts/start-kiosk.sh` 開 `/stage.html?kiosk=1`，舞台自動連線並退避重連；
   一般開啟舞台維持點擊進入。
4. 訪客對話重置：舞台上一輪結束後閒置 N 秒（預設 10，控制台可設 3–300），清除舞台畫面、
   對話歷史與已顯示看板項目；訪客開始說話、新輪次、斷線都會取消倒數；控制台不受影響。

5. 後端關閉：SIGTERM／SIGINT 由伺服器事件迴圈接手，先關閉 WebRTC 連線與語音工作階段再停
   owned llama-server；關閉期間的重複訊號忽略，15 秒期限保底。修正前完成過對話的後端收到
   SIGTERM 會卡在非 daemon 執行緒，必須 SIGKILL。

6. Edge TTS 首音韌性：預先備妥並重用 WebSocket 連線（`src/tts/edge_connection.py`）；429 短暫退避並多一次嘗試；
   預取最多一段。延遲根因量測為建立連線時的網路偶發停頓（1–10 秒）與服務端限流；程式碼僅放大
   （每段新連線、固定 2.5 秒逾時後才重建連線、預取併發）。對沖第二條連線實測無效，未採用。

## 暫緩（詳見 issues/）

認證與綁定位址、錄影路由、場域內容範圍、開機自啟與復原、驗收標準。
公共空間誤觸發先接受，試營運現場調整麥克風與 VAD 門檻後再評估是否加喚醒。
