<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->

# 固定文字朗讀

Jetson 上先使用以下入口，驗證固定回答的畫面與聲音連續性：

```bash
bash scripts/start-jetson.sh --read-aloud
```

開啟 <https://localhost:3000>，選擇「朗讀模式」，啟動連線後輸入固定
文字並按「開始朗讀」。朗讀不需要麥克風；若瀏覽器詢問權限，可以拒絕，
控制台會使用接收影音的連線。需要原有舞台背景時，在數位人設定選擇背景。

此入口使用 `config/config_jetson_read_aloud.yaml`：直式 720×1280、
25fps、batch 8、TensorRT UNet 與 TAESD 輕量嘴型解碼。它忽略已保存
的模型覆蓋設定，不載入 LLM、VAD 或 ASR；已保存的對話設定仍可在一般
啟動入口使用。`--realtime` 也使用直式 720×1280 診斷設定。

一般 Jetson 入口使用直式 720×1280、TensorRT UNet 與 TAESD，
並保留已保存的 LLM、語音輸入與舞台設定，可供對話和朗讀共用：

```bash
bash scripts/start-jetson.sh
```

Jetson 入口把小型 CPU 運算的執行緒池預設為 1，避免 FFT、BLAS 與
OpenCV 工作者和 RTP 排程爭用 CPU。需要調整時可設定
`NOVA_AVATAR_CPU_THREADS`；此設定只套用於本次啟動的服務。

變更設定檔後須重新啟動後端；網頁切換「朗讀模式」不會切換模型
推理設定。舊的未加速 Jetson 設定只有約 7.4fps，renderer 等待期間
會補入靜音，曾把約 5.68 秒回覆拉成 19.3 秒，即使網路未丟包也會
斷續。此次追查見 [電子音診斷](../.scratch/recording-stutter/audio-report.md)。

TAESD 是近似解碼，牙齒與唇部細節較柔；提高輸出解析度不會恢復完整 VAE 的細節。
需要 `.local/jetson/taesd/` 與本機 TensorRT UNet engine，準備方式見
[既有即時生成文件](realtime-avatar.md)。若模型回退原始推理路徑，
不能沿用加速測試的效能結論。

2026-10-02 實測包含有畫面的 Chromium、原舞台背景、三輪完整固定回答。
結果與限制見 [錄影卡頓診斷](../.scratch/recording-stutter/report.md)。

目前最低解析度與 LFM 模型測試見 [720p／1080p 實測報告](lfm-resolution.md)。
上述較低解析度的測試不代表現在的 720p 已通過流暢標準。

## 播放修正與重測

視訊時間戳按實際釋放時間推進，避免每次等待的微小誤差累積成突然
跳過三個 RTP 時間槽。音訊主時鐘與影格釋放間隔限制保留。
音訊佇列暫時沒有 PCM 時，只等待下一個封包期限前的剩餘時間；
編碼耗時不再額外疊加到原有 20ms 封包間隔，避免接收端因封包
持續偏慢而補音。

控制台和獨立舞台對支援的瀏覽器設定音訊接收緩衝目標 160ms；視訊
仍使用瀏覽器的自適應緩衝與影音同步。不支援此設定時，保留瀏覽器
原有行為。這是接收端的播放延遲取捨，不等待嘴型生成。
相較原先 80ms，多留約 80ms 應對 LLM 與嘴型同時推理的短暫抖動。
API 語意見 [W3C WebRTC](https://www.w3.org/TR/webrtc/#dom-rtcrtpreceiver-jitterbuffertarget)。

正式路由、PCM 完整性與影音配對：

```bash
NOVA_AVATAR_RUNTIME_OVERRIDES_ENABLED=0 uv run python \
  .scratch/read-aloud/playback.py \
  --config config/config_jetson_read_aloud.yaml \
  --output .scratch/recording-stutter/read-aloud-final.json
```

此測試會載入另一份模型；執行前先停止網頁服務，避免同時渲染。
啟動加速服務後，瀏覽器三輪驗收可使用：

```bash
uv run --with playwright python .scratch/recording-stutter/browser_probe.py
```

瀏覽器測試使用獨立暫存設定與假麥克風，不擷取使用者語音。檢查實際
呈現影格計數、畫面更新間隔、近似相同影格、凍結與音訊遺失補償。
主執行緒可能漏掉影格 callback，因此影格率使用
[`presentedFrames`](https://wicg.github.io/video-rvfc/#dom-videoframemetadata-presentedframes)
計數，另保留 callback 與影格樣本。

## 畫質設定恢復對照

2026-10-02 在所有音訊修正保留的條件下，逐項恢復原解析度、完整
VAE 與 PyTorch UNet。三項都重新出現音訊拉長或缺音補償，因此一般
當時入口保留 450 高度、TAESD 與 TensorRT UNet；這是歷史測試設定。播放設定從未調降，
仍為原本的 25fps。完整數據、失敗結果與前後試聽已整理為
[HTML 報告](../web/public/reports/avatar-smoothness-report.html)；服務啟動後
可開啟 <https://localhost:3000/reports/avatar-smoothness-report.html>。

本次基準畫面取樣低於前次測試，報告明確分列音訊與畫面驗收；
不以先前通過結果代替本次未過關項目。原始對照位於
`.scratch/quality-restoration/`。
