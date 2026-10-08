<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->

# 不使用 LLM 的數字人即時生成驗證

2026-10-01，Jetson AGX Orin 64GB、MODE_50W、GPU 上限 816MHz。
MuseTalk `musetalk_1`、FP16、batch 8、25fps，Edge
`zh-TW-HsiaoChenNeural`。本輪所有數字人實測均未載入或呼叫 LLM。

## 結果

加速模式已通過固定 PCM 與即時固定回答 TTS 的完整 WebRTC 驗收。
使用 **720p、TensorRT UNet、TAESD 近似解碼器**，並修正首批、分段
與媒體時鐘排程。需明確選用此 profile；完整 VAE 在目前硬體功耗
設定下仍無法達到同樣的即時速度。

| 實驗 | PCM 長度 | 實際播放 | 文字／送入到首音 | 標記 PCM 最大間隔 | A/V 釋放偏差 P95 | 驗收 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 修改前，960p、既有 TRT 完整 VAE | 9.08s | 21.1421s | 1.0876s | 632.91ms | 841.41ms | 失敗 |
| 加速設定，正式載入流程，固定 PCM 重播三次 | 27.24s | 27.2399s | 0.7048s | 28.70ms | 52.35ms | 通過 |
| 即時 TTS，完整固定回答一次合成 | 10.30s | 10.2957s | 1.2716s | 29.38ms | 68.52ms | 通過 |
| 即時 TTS，三片段，最終首批與銜接修正 | 9.08s | 9.0879s | 1.2673s | 28.25ms | 55.02ms | 通過 |

正式載入流程的 PCM 測試對應嘴型覆蓋率 98.09%；最終三片段 TTS
為 97.80%，PCM 就緒到首音 0.7809s。所有標記 PCM 均完整送出，
兩個加速 adapter 都實際載入，沒有發生回退。允許少量晚到嘴型
影格依既有策略丟棄；沒有透過丟棄語音或大量重複同一張嘴型取得通過。

固定文字：今天的測試會先確認聲音是否連續。接著比較嘴型推理造成
的等待。最後記錄整段語音的播放時間。完整合成與分段合成的語調、
停頓與 PCM 長度不同，因此分別記錄。

原始 JSON：

- [修改前基準](baseline.json)
- [正式載入、27 秒固定 PCM](production-replay.json)
- [完整回答即時 TTS](single-tts-playback.json)
- [最終三片段即時 TTS](complete-tts-playback.json)

## 瓶頸與改善

1. **完整 VAE 解碼太慢。** 同機 batch 8，PyTorch VAE 約 865ms；
   既有 TRT 約 422ms，重新選 tactics 後仍約 336ms。25fps 的八張
   影格只有 320ms 預算，完整 VAE 單獨就超過預算。
2. **UNet 推理成本。** FP16 TensorRT 保留相同零 timestep 模型，
   實測約 152–162ms／八張，比 PyTorch 的 259–285ms 更快。
   用原 VAE 解碼比較 UNet 輸出，PSNR 約 57.7dB，通過 35dB
   數值品質門檻。[數值比較](unet-comparison.json)。
3. **輕量解碼。** TAESD 約 87ms／八張，保留原素材編碼與縮放
   契約。它是近似模型：與原解碼器 PSNR 約 30.06dB、平均像素
   差約 4.91／255，**未通過原 VAE 的 35dB 等效門檻**。臉部
   身分與口形仍可辨識，但牙齒與唇部細節較柔；需明確選用。
   [比較數據](tiny-times.json)、[臉部比較](crop-comparison.jpg)。
4. **CPU 合成與編碼。** 720p 背景合成約 8.3ms、H.264 約 11ms
   中位數，減少與特徵提取執行緒競爭。全解析度 1080×1920
   的合成仍有獨立效能問題，不能宣稱全解析度已即時。
5. **音訊時鐘。** renderer 缺資料時，音訊曾停止、視訊重複卻持續
   前進；恢復後視訊被排到過晚。現在兩種音訊模式缺資料時均補
   未標記靜音，維持權威時鐘，保留已排隊語音順序。
6. **無謂節流。** 視訊佇列滿時，特徵執行緒原本即使有 PCM 也
   額外睡眠最多 192ms。現在只在沒有待處理 PCM 的待機時節流，
   語音由現有有界佇列控制。
7. **首批語音不足。** 暖機的十個待機右側 context 佔掉首批位置，
   只留下六個語音 PCM 幀、120ms，無法覆蓋下一批推理。現在只
   重建未標記的待機 lookahead，保留左側歷史與全部語音順序；
   TTS 首包不足時，首批先等完整窗口，已完成的短句仍能立即排出。
   等待發生在尚未送出任何語音的首次起音，媒體時鐘持續待機。
8. **分段 TTS 釋放太晚。** 下一段已預取完成，仍等上一段最後一幀
   播完才入列，導致每段重新等待推理。現在上一段 PCM 全部入列
   後，下一段可直接接續進同一有界 FIFO；最後一段仍等播放結束，
   取消、提交與片段順序檢查保留。
9. **取消競態。** Python 3.10／3.11 的 `asyncio.wait_for` 在 queue
   read 同時完成時會吞掉取消，造成 RTP 關閉卡住。改用明確的
   queue task 與 `asyncio.wait`，在清理時保留取消訊號。

音訊時鐘、首批配對、片段順序與取消競態都有先失敗、修正後通過的
回歸重現；短句、adapter 回退與正式設定載入也納入測試。

## 未採用的路線

- channels-last 加 cuDNN autotuning 的微型測試快，但實際 render
  worker 首次呼叫有約十秒暖機，端到端未通過，因此未加入正式設定。
- TAESD FP16 TensorRT 在此 TensorRT 10.16.2 環境遇到 CASK shader
  建置 assertion；強制 FP32 雖能建置，八張約 142ms，慢於 PyTorch
  TAESD 的 82ms，因此使用 PyTorch 輕量解碼。
- CPU threads 1 沒有改善首批間隙，因此沒有更改程序的 CPU thread
  預設。最後透過正確的首批窗口與片段釋放消除間隙。
- 獨立 PCM 提早播放曾讓嘴型同步失敗；正式驗證仍走配對 renderer
  與音訊主時鐘，沒有透過此模式取得即時通過。

## 資源與量測限制

實測跑到 aiortc 接收與解碼，包含 Whisper 特徵、UNet、VAE、貼臉、
背景合成、軟體 H.264、WebRTC。A/V 配對使用 fragment 和 media
sequence；每個影格只計第一次釋放，重複影格不重複增加覆蓋率。
表格從模型載入、暖機與 WebRTC 連線完成後，送入文字或 PCM 起量測；
首音時間不包含服務冷啟動與模型載入。
自然語句停頓會使接收端「非靜音」幀出現間隔，因此連續性驗收使用
全部標記 PCM 的釋放與完整性，並另保留接收端數據。

修改程式時背景 codebase-memory 自動索引曾占用約 600–700% CPU，
能干擾即時量測。最終三片段驗證暫停此 Codex 索引程序，以 shell
EXIT trap 自動恢復；已確認恢復。未停止其他使用者程序。
GPU 實測與全套 pytest／前端 build 分開執行。

本輪不包含 VAD、對話 ASR、瀏覽器顯示、喇叭、外部網路或 LLM
共跑，不能當作完整語音對話的 P95。先前 LLM 競爭結果見
[前次診斷](../fixed-reply-diagnosis/report.md)，本輪沒有重跑 LLM。

## 驗證與使用

- `uv run python scripts/check-integration.py`：通過，含品牌與授權檢查。
- `uv run pytest`：485 通過、4 略過、1 失敗。失敗為本輪開始前已
  存在的 `test_chroma_composite_fits_the_render_frame_budget_on_a_portrait_avatar`；
  全解析度合成中位數 35.09ms，門檻 30ms。本輪未修改合成算法或
  放寬此門檻。[完整紀錄](pytest-full.log)。
- `cd web && npm test`：84 通過。
- `cd web && npm run build`：通過；保留既有 bundle 大小提示。
- `git diff --check`：通過。

可重跑命令、模型下載及固定回答用法見
[使用文件](../../docs/realtime-avatar.md)。
加速設定為 [config_jetson_realtime.yaml](../../config/config_jetson_realtime.yaml)。
模型與本機 engine 已備妥於 `.local/jetson/`，不加入 Git；啟動此
診斷 profile 時必須設定 `NOVA_AVATAR_RUNTIME_OVERRIDES_ENABLED=0`，
避免控制台保存的 llama.cpp 選項蓋過診斷設定而載入 LLM。
