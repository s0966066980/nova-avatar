<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->

# 預錄呈現實作驗證 — 2026-10-13

功能已接入，以下區分已實測結果與仍待確認的驗收。
設計訪談時的基線保留在 [設計基線](design-baseline.md)。
本文保留首次功能驗收的結果與當時設定；後續操作問題、最新測試數
與保留設定見 [操作修正驗證](../fixes/README.md)。

## 實機與素材

NVIDIA Jetson AGX Orin Developer Kit、Jetson Linux R39.2.1、50 W 模式、
X11 本機可見 Chromium 154.0.8037.97；WebGL 使用 NVIDIA Tegra Orin。
角色 `musetalk_1`，待機與說話素材都是 1080×1920、25 fps、無音軌。
五秒說話素材使用目前 TTS 與完整 MuseTalk VAE，125 影格，製作約
68.2 秒，保留來源綠幕；來源角色檔案保持完整。

[素材製作報告](../live-assets.json)、[環境](environment.json)、
[單畫面瀏覽器報告](../browser-45-seconds.json)。

## 最終十分鐘雙畫面

兩個可見 Chromium 視窗、1080×1920、動態背景。舞台連續錄影十分鐘，
控制台另錄約 30 秒；兩端反覆朗讀、LLM 回覆與中斷。
開發用程式索引工作暫停，測試結束已恢復；保留原有遠端桌面、
RAGFlow、Ollama 與目前 LLM／TTS 等服務。詳細設定見環境檔。

| 實測 | 控制台 | 舞台 |
| --- | --- | --- |
| 平均畫布更新 | 25.002 fps | 24.999 fps |
| 最大更新間隔 | 50.1 ms | 66.7 ms |
| 素材解碼丟幀 | 0 | 0 |
| MP4 有效影格率 | 25.027 fps | 24.999 fps |
| MP4 長度／影格數 | 29.05 秒／728 | 600.26 秒／15007 |
| 接收音訊補音總量 | 1649 樣本，約 34 ms | 3387 樣本，約 71 ms |

畫面與錄影的平均 ≥24 fps、最大間隔 ≤200 ms 門檻通過。
兩端均成功匯出 H.264 1080×1920／AAC MP4，音軌與影像結尾差
不到 8 ms。[瀏覽器報告](../browser-600-seconds.json)、
[舞台錄影檢查](stage-record-check.json)、[控制台錄影檢查](console-record-check.json)。

補音計數含整個連線，未區分靜音與有聲樣本；沒有逐字比對參考 PCM，
也未測真實麥克風與實體揚聲器。因此不宣稱語音完全沒有缺樣本，
或所有硬體／瀏覽器都有同樣表現。人物淡接開始對接收 PCM 的
中位差為控制台 -83.6 ms、舞台 -40.0 ms；極值 -210.3 到 +60.7 ms，
另有 100 ms 人物淡接，符合通用說話動作但不等於逐字同步。

初次版本確實未達門檻：雙端約 23.5／20 fps、266.7 ms 停頓，
並遇到重編碼的時間戳錯誤；已修正取幀、H.264 選擇／保留原影像
與接收端時序。保留 [初次報告](../browser-600-initial.json) 供對照，
沒有放寬門檻或靜默載入 MuseTalk。

## 已完成的回歸與介面檢查

| 檢查 | 結果 |
| --- | --- |
| 整合／品牌／授權檢查 | 通過 |
| Python 全套 | 560 passed、4 skipped、1 既有失敗 |
| 前端全套 | 100 passed |
| 前端建置 | 通過；既有大 chunk 警告 |
| 設定介面 | 1440、375、812 px，無溢出或頁面錯誤；早期關閉預覽有清理 |

Python 的唯一失敗仍是原有全尺寸 CPU 綠幕合成預算：
`test_chroma_composite_fits_the_render_frame_budget_on_a_portrait_avatar`，
本次中位數 35.44 ms，門檻仍為 30 ms，未修改。完整輸出保留於本機
`pytest-final.log`、`web-tests-final.log`、`web-build-final.log` 與
`integration-final.log`；介面結果見 [介面](settings-report.json)。

初次錄影掉幀的對照：定時取幀約 22 fps；每次渲染完成後明確取幀，
MP4 與 WebM 都約 25 fps。此 Chromium 原本以通用 MP4 選到
VP9／Opus；已改優先 H.264／Opus，輸出時保留 H.264 影像，僅將
Opus 轉 AAC。[取幀對照](capture-comparison.json)。

收到的音訊與時鐘影像在冷啟動有不同抖動緩衝，僅使用解碼影像時鐘
會提早開口。現在以兩軌 `estimatedPlayoutTimestamp` 差值修正，
等 RTCP 時鐘就緒再消費事件。最終單畫面短測首次開口與接收 PCM
差約 +22.5 ms；後續切換為 -128、-15.7、-99.1 ms，此為人物淡接
開始時間，淡接本身另需 100 ms。不是逐字嘴型或零誤差承諾。

## 狀態與限制

模式往返 MuseTalk → 預錄成功，兩者健康檢查就緒；預錄模式已重啟
多次驗證保存設定、無嘴型模型啟動。素材還原、缺件、取消、失敗、
重啟清理、斷線互斥與原始錄影保留有集中回歸。
[模式往返](mode-roundtrip.json)；功能／既有語音回歸輸出保留於本機
`focused-regression.log`。

最終保留原角色的 MuseTalk／540 高度與原背景，待機與說話示範素材
仍已準備好，可在控制台選預錄後手動調到 1080p。測試背景已移至
回收區，沒有修改原角色來源。工作區既有 RAGFlow／TTS 修改保留。

本輪未完成真實麥克風、實體揚聲器及參考 PCM 全長比對，這些仍是
完整語音驗收的限制。新版 H.264 雙端同時長時間錄影也未作為主門檻；
主測是一端持續錄影、另端短錄。若背景索引或其他 GPU 工作同時運行，
請另測或手動降低畫質。此功能不承諾其他負載下固定無卡頓。
