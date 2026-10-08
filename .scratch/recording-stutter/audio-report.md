<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->

# Chromium 回覆斷續與電子音追查

使用者在 Chromium＋電腦喇叭實測，朗讀及對話均有斷續電子音。
先前通過的是隔離 LLM 的 `--read-aloud` profile，沒有涵蓋再次使用
一般 Jetson 啟動入口的情況。不能用先前的零凍結統計代表這次音質。

## 重現

回放本次使用者實際操作的音訊提交日誌：

```bash
uv run python .scratch/recording-stutter/audio_log_gate.py \
  logs/nova-avatar_2026-10-02_11-25-05.log
```

四段回覆皆不合格；其中兩段對話的標記 PCM 都是 5.68 秒，實際
提交跨度卻是 19.291、19.309 秒。較短朗讀也被拉成 3.38～3.73 倍。
此日誌是問題發生時的資料，早於本次測試與背景負載。

同一固定文字在舊服務的實際 Chromium AudioWorklet 擷取也失敗：
原始 Edge TTS 10.992 秒，回覆有效音訊跨度 32.639 秒，
`concealmentEvents=22`、`concealedSamples=331018`、網路丟包 0。
[基準資料](audio-before.json)、[基準音訊](audio-before.wav)。

推理只有約 7.4fps；正在執行的程序是 `config/config_jetson.yaml`，
沒有設定 TensorRT UNet、TAESD 或輸出高度限制。
`BaseAvatar.process_frames` 等待 MuseTalk 推理結果才能送出該影格
的兩個 PCM chunk；`PlayerStreamTrack.recv` 佇列耗盡時補入未標記
靜音。封包仍正常送出，因此不能只靠 `concealedSamples` 判定音質。

瀏覽器的缺音補償、播放加減速定義見
[W3C WebRTC Stats](https://www.w3.org/TR/webrtc-stats/#dom-rtcinboundrtpstreamstats-concealedsamples)。

## 採用修正

- 將既有加速路徑放入一般 `config/config_jetson.yaml`：TensorRT UNet、
  TAESD；最終一般模式最大高度 450，專用朗讀仍為 540。
  保留 LLM、語音輸入及已保存的舞台設定。
- `scripts/start-jetson.sh` 一般入口顯示正在使用的加速設定。
- 新回歸測試經正式 config loader／model factory，修正前確認會
  選原模型（失敗），修正後確認兩個加速器與輸出高度有傳入。
- 沒有改成已知未通過聽感／A/V 驗收的 direct PCM 實驗路徑，
  也沒有把語音靜音補償視為正常回答內容。
- 修正 audio dequeue 等待時間：`recv()` 在 Opus 編碼後再次執行，
  只能花下一個音訊期限前的剩餘時間等待 PCM，不能重新等滿 20ms。
  原先每輪 8ms 編碼使空佇列封包間隔變成 28ms；新回歸測試走
  真正 `recv()`，確認 20 個封包維持 20ms 間隔及零時鐘重設。
  取消處理、有效語音順序及既有 stall 重設規則保留。
- 收音暫停時繼續接收並丟棄 uplink 音訊，但不重採樣；原先每秒
  50 次無用 executor 來回會佔用相同媒體 event loop。
  此情境先以 20 個暫停音框重現 20 次重採樣，再確認修正後為 0；
  正常收音與插話測試仍通過。
- 音訊接收緩衝目標從 80ms 改為 160ms，視訊仍保持自適應。
  約增加 80ms 播放延遲，吸收長回答中 LLM 與嘴型推理重疊的
  抖動；正式 ontrack 的回歸先確認 80 不符合 160，再修正通過。
- Jetson 入口將 OMP、OpenBLAS、MKL 與 OpenCV 的 CPU 工作者預設
  為 1（可用 `NOVA_AVATAR_CPU_THREADS` 覆蓋），減少小型 FFT／
  縮放工作對媒體 event loop 的干擾。原執行緒池為 12，實測 CPU
  曾全核滿載；相同設定下只增加接收緩衝仍未通過正式頁面閘門。
  [160ms／CPU12 中間結果](browser-buffer160-cpu12.json)。

僅套加速設定的中間實驗仍未過關：有效語音跨度 10.896 秒，但
缺音補償仍有 6 次，音訊時鐘重設 49 次，因此繼續修正 dequeue
期限，沒有把中間改善宣稱為完成。[中間資料](audio-after.json)。

## 音訊驗收方式

`audio_probe.py` 使用正式前端 `useWebRTC` 與 `/offer`、`/human`
路由，透過 AudioWorklet 擷取收到的數位人音訊。測試明確拒絕
取得麥克風，僅儲存人工測試文字的合成回覆；沒有錄製使用者語音。
原始 Edge TTS 使用同一文字及聲音另存 `audio-source.mp3`／`.wav`。

閘門除了缺音補償，也檢查回覆有效音訊起訖跨度不得超過原始 TTS
時長 15%，以攔截伺服器自行插入靜音、但瀏覽器沒有丟包的情況。
此閘門檢查連續性，不宣稱等同於人工聽感或實體喇叭驅動驗證。

## 正式重啟後的結果

使用無參數的 `bash scripts/start-jetson.sh` 啟動，LLM 正常載入；
語音輸入停用狀態、LLM 與舞台設定沿用使用者原有值。日誌確認
TensorRT UNet 與 TAESD 真正啟用，沒有暫停背景索引來美化結果。

正式控制台（有麥克風音軌）三輪固定朗讀，全部通過原有門檻：

| 輪次 | 呈現 fps | 最大畫面更新間隔 | 音訊補償 samples | 凍結 | 掉幀 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 23.98 | 83.3ms | 0 | 0 | 0 |
| 2 | 24.47 | 66.8ms | 0 | 0 | 0 |
| 3 | 24.45 | 66.7ms | 0 | 0 | 0 |

[正式頁面樣本](browser-playback.json)、[畫面](browser-after.png)。
沒有調降 23fps、120ms、零缺音補償及零凍結的門檻。
較早 540 一般模式在同一頁面仍有 22～23fps 及少量缺音，
因此最終把一般模式調至 450，並略過暫停收音的無用重採樣。
[540 有麥克風結果](browser-with-mic-before.json)、
[540 無麥克風結果](browser-without-mic-before.json)。
CPU1 首次測試的聲音補償與視訊凍結均為 0、約 24fps，但第一次
callback 取樣有 133ms 間隔，仍如實記為閘門失敗，沒有放寬標準。
原條件重測三輪全部通過，以上表格為重測結果。
[CPU1 首次樣本](browser-cpu1-first.json)。

| 實測 | 回覆有效音訊跨度 | 缺音補償次數 | 補償 samples | 丟包 | 視訊凍結／掉幀 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 修正前同一段朗讀 | 32.639 秒 | 22 | 331018 | 0 | 0／0 |
| 修正後朗讀 | 9.488 秒 | 0 | 0 | 0 | 0／0 |
| 修正後 LLM 對話 | 19.803 秒 | 0 | 0 | 0 | 0／0 |

原始 TTS 含前後靜音，朗讀檔全長 10.992 秒。表格取接收音訊
首次至最後超過音量閾值的跨度，因此不包含請求等待與尾端靜音，
也不把瀏覽器的正常播放加減速假裝成逐樣本相同。
同一朗讀的伺服器標記 PCM 約 10.3 秒，期限修正後的早期擷取
在約 10.26 秒內送完，時鐘重設從中間實驗的 49 次降至 1 次。
LLM 長回答初次在 80ms target 下仍有 2 次缺音補償，因此續改
160ms，再測更長回答（原始 TTS 27.528 秒）才通過。最終 CPU1
服務的另一段較長對話也通過（原始 TTS 22.272 秒）；音訊 sample
及表格已更新為這次擷取。
[長回答 80ms 實驗](audio-chat-buffer80.json)。

- [修正後朗讀資料](audio-final-echo.json)／[接收音訊](audio-final-echo.wav)
- [修正後對話資料](audio-final-chat.json)／[接收音訊](audio-final-chat.wav)
- [伺服器提交時長](audio-final-timing.json)

## 驗證與範圍

- 聚焦 Python（含正常收音、暫停及插話）：102 通過、12 subtests 通過。
- 最後啟動入口聚焦檢查：21 通過。
- 整合、品牌及授權檢查：通過。
- 最終 Python：495 通過、4 略過、1 失敗。失敗仍是原尺寸背景
  合成既有效能測試，約 43.08ms 高於 30ms；沒有放寬門檻。
- 前端 84 通過；build 通過，保留既有 bundle 大小提示。
- `git diff --check` 及啟動腳本語法：通過。

測試只擷取人工輸入的合成回覆；對話走真實本機 LLM，沒有模型
mock。未宣稱實體喇叭、作業系統音效驅動、錄屏、多會話或外部
網路下永遠零失真。保留舊工作目錄修改，未提交或重置。
