<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->

# 固定回答的錄影卡頓診斷

2026-10-02，Jetson AGX Orin、MODE_50W；單一固定文字朗讀會話。

本報告前段記錄凌晨的隔離朗讀修正。使用者後續在一般模式仍聽到
電子音，另已重現及修正音訊 dequeue 期限、一般啟動設定與暫停
收音的多餘工作；最新結果見 [電子音追查](audio-report.md)。

## 已重現的問題

原始錄影 `outgoing_96336793_20261002014535438_display0_av1.webm`
長 52.337s，只有視訊軌，不能用它判定聲音連續性。
錄屏平均 16.80fps、最長影格間隔
508ms；人物 ROI 的近似靜止區間最長
1.407s。ROI 比較是近似靜止偵測，不宣稱每張圖逐像素完全相同。
[量測資料](recording-analysis.json)。

錄影時段後端仍使用 `config_jetson.yaml`，嘴型推理日誌約
6.8–7.6fps，低於 25fps。正式 `/human type=echo` 在完全不呼叫
LLM 的對照也失敗：同一 10.30s PCM 花
33.05s 播完，最大標記音訊間隔
1084ms。這確認原始生成／輸出路徑本身會
卡頓，不能只歸因於網路或錄屏。[原設定對照](read-aloud-original.json)。

另外，視訊的 40ms 釋放下限與理想影格計數共同累積 scheduler
誤差；每次睡眠多 1ms，160 張影格即可造成 160ms RTP 時間戳跳躍。
`test_video_scheduler_jitter_does_not_create_periodic_rtp_gaps` 先失敗，
修正後通過；既有真正停頓恢復與防止突發影格測試仍通過。

## 採用的修正

- 視訊依實際釋放時間更新 PTS，保持單調、40ms 釋放下限與共同
  音訊時鐘；避免微小誤差被累積成突然跳過三個時間槽。
- `config_jetson_read_aloud.yaml` 使用高度 540、batch8、25fps、
  TensorRT UNet 與 TAESD；540 降低背景合成、編碼與瀏覽器負擔。
  原 720 診斷 profile 保留。
- 控制台與獨立舞台使用相同音訊接收設定：支援時設定
  初始 `jitterBufferTarget=80` 毫秒，後續電子音追查調整為 160ms；
  視訊保留自適應緩衝。
  設定不支援或 setter 失敗時沿用瀏覽器預設，不影響連線。
  [W3C API 契約](https://www.w3.org/TR/webrtc/#dom-rtcrtpreceiver-jitterbuffertarget)。
- `--read-aloud` 啟動入口忽略保存的 LLM 覆蓋、不載入 LLM、VAD、
  ASR，並保留一般對話與原 `--realtime` 入口。

兩個可重現回歸先失敗再通過：視訊微小排程誤差與實際 `ontrack`
音訊接收緩衝設定。新的朗讀啟動入口也測過保存的 llama.cpp 設定
不會蓋過診斷 profile。

## 完整 PCM 與嘴型配對

正式路由、TTS、真實模型、背景合成、H.264 與 aiortc 接收解碼：

| 項目 | 最終結果 |
| --- | ---: |
| 合成／送出 PCM | 10.30s / 10.30s |
| 實際播放 | 10.334s |
| 最大標記音訊間隔 | 33.16ms |
| 嘴型對應覆蓋率 | 97.86% |
| A/V 釋放偏差 P95 | 64.18ms |
| 驗收 | 通過 |

兩個加速 adapter 均實際使用、沒有回退，全部 PCM 送出。
[完整資料](read-aloud-final.json)。

## 瀏覽器播放

有畫面的 Chromium，原錄影使用的舞台背景，同一固定文字三輪；
測試走正式前端朗讀按鈕、HTTP 路由及 WebRTC，不在 harness 代替
產品設定接收緩衝。最新音訊 target 為 160ms，視訊為 null。
下表已更新至音訊期限修正後的 450 一般模式，LLM 保持載入；
原先隔離朗讀的測試條件與這個一般模式不同。

| 輪次 | 呈現 fps | 最大 callback 間隔 | 凍結次數 | 音訊補償 samples |
| --- | ---: | ---: | ---: | ---: |
| 1 | 23.98 | 83.3ms | 0 | 0 |
| 2 | 24.47 | 66.8ms | 0 | 0 |
| 3 | 24.45 | 66.7ms | 0 | 0 |

三輪均通過：呈現 >=23fps、callback 間隔 <=120ms、近似相同人物
區域 <=250ms、凍結與音訊補償均為零。此次瀏覽器掉幀也為零。
[瀏覽器完整樣本](browser-playback.json)、[畫面](browser-after.png)。

影格率按 compositor 的 `presentedFrames` 計數，而非 callback
次數；callback 可漏取樣，前幾次探測的 callback fps 因此低估呈現
影格率。仍保留間隔、像素取樣與凍結計數，不放寬驗收門檻。
[影格 API 契約](https://wicg.github.io/video-rvfc/)。

測試固定文字：今天的測試會先確認聲音是否連續。接著比較嘴型推理造成的等待。最後記錄整段語音的播放時間。

## 驗證、資源與限制

以下為凌晨隔離修正的驗證記錄；一般模式的最新檢查見電子音追查。

- 聚焦 Python：98 通過、12 subtests 通過；後續入口參數測試含
  新 540 profile，也納入最終全套檢查。
- 整合、品牌與授權：通過。
- 最終 Python：492 通過、4 略過、1 失敗。失敗是本輪開始前已
  存在的原尺寸綠幕合成效能測試，35.07ms 超過 30ms；沒有改該算法
  或放寬門檻。540 朗讀路徑已通過上方實播驗收。
- 前端：84 通過；正式 build 通過，保留既有 bundle 大小提示。
- `git diff --check` 與啟動腳本語法：通過。

TAESD 是近似解碼，唇齒細節較柔；540 輸出放大後也較柔。
這次沒有啟用 LLM、ASR、多會話、外部網路或 AV1 桌面錄屏；
也沒有用統計零補償宣稱人工聽感或所有負載下永遠零卡頓。
獨立舞台已接入同一緩衝 helper，瀏覽器三輪實播測的是控制台。

效能量測時暫停本機 codebase-memory 索引 daemon 與其 worker，
以 shell EXIT trap 恢復；全套測試、build 與 GPU 實播分開執行。
背景索引會有大量 CPU 負載，不能忽略它對即時播放的干擾。
原有工作目錄修改保留，沒有提交或重置。

日常用法與重測命令見 [固定朗讀文件](../../docs/fixed-read-aloud.md)。
