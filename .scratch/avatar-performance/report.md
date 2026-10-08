<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->

# Nova Avatar 播放效能測試 — 2026-09-30

解析度控制與可選 TensorRT VAE 已完成實測。音訊獨立排程能消除這次
本機重播的音訊停頓，但嘴型同步未通過驗收，仍保持實驗狀態。
本次未修改啟動中的 server 或 `config/config_jetson.yaml`。

## 測試環境與範圍

- Jetson AGX Orin 64GB，MODE_50W；GPU 上限 816MHz。
- 既有 MuseTalk FP16 UNet/VAE、`musetalk_1`，batch 8，素材 1080×1920。
- PyTorch 2.11.0/cu130、CUDA 13.2、TensorRT runtime 10.16.2.10。
- 本機 aiortc WebRTC peers，H264 編碼、遠端 audio/video 真實解碼。
- 確定性 220Hz 連續音，16000Hz PCM、每幀 320 samples；背景使用固定灰色。
- 每個 GPU 實驗依序執行；前端測試與完整 pytest 在 GPU 實驗結束後執行。
- 沒有測 LLM、ASR、遠端 TTS、真人語音聆聽或跨網路瀏覽器長時間播放。

## 解析度控制

`video.max_height` 在嘴型貼回及轉場之後、背景合成及編碼之前生效。
保留比例、不放大；`0` 保留原尺寸。既有 width/height 不改變語意。

真實角色首幀，含 resize、背景陣列建立及 chroma composite；暖機後
7 次取中位數。此處不包含嘴型推理與 H264 編碼。

| 輸出 | 縮圖加合成中位數 | P95 |
| --- | ---: | ---: |
| 1080×1920 | 49.66 ms | 51.01 ms |
| 720×1280 | 21.29 ms | 22.79 ms |
| 540×960 | 11.69 ms | 11.73 ms |

來源：[resolution-comparison.json](resolution-comparison.json)。

## VAE 加速

本機 TensorRT 引擎輸入 FP16 latent，batch profile 1–8。
使用實際角色 latent 及 UNet 輸出；暖機後各 3 次取中位數，包含
CPU 圖片轉換並在計時邊界同步 CUDA。

| Batch | UNet | 原始 VAE | TensorRT VAE | VAE 加速 | PSNR |
| --- | ---: | ---: | ---: | ---: | ---: |
| 4 | 151.56 ms | 389.61 ms | 190.25 ms | 2.05× | 59.28 dB |
| 8 | 233.43 ms | 777.19 ms | 384.46 ms | 2.02× | 59.28 dB |

每通道平均絕對誤差為 0.077/255，這些樣本通過 PSNR ≥35dB 的數值門檻。
數值門檻不代替真人角色的目視驗收。batch 8 的 UNet + VAE 仍約 618ms，
僅模型部分約 13fps，尚未達到 25fps；Whisper、貼回與編碼還有額外成本。

來源：[vae-comparison.json](vae-comparison.json)。

較高 builder 搜尋強度超過十分鐘後停止；降低至 level 0、maxTactics 1
後約 113 秒完成。本機 Py3.11 環境另外安裝了
`onnx==1.17.0`、`protobuf==4.25.9` 與
`tensorrt-cu13-bindings==10.16.1.11`；未改動專案依賴宣告。

可重建命令（需先有本機 TensorRT runtime 與對應 Python bindings）：

```bash
.venv/bin/python .scratch/avatar-performance/export_vae.py
timeout 240s /usr/src/tensorrt/bin/trtexec \
  --onnx=.scratch/avatar-performance/vae.onnx \
  --saveEngine=.scratch/avatar-performance/vae.engine \
  --minShapes=latents:1x4x32x32 --optShapes=latents:4x4x32x32 \
  --maxShapes=latents:8x4x32x32 --fp16 \
  --memPoolSize=workspace:1024 --builderOptimizationLevel=0 --maxTactics=1 \
  --skipInference
.venv/bin/python .scratch/avatar-performance/compare_vae.py
```

引擎僅適用於匹配的 GPU、runtime 與模型權重，產物未納入 Git。
載入或執行失敗會回退原始 VAE。

## 完整播放對照

每組注入相同 2 秒 PCM。表中的「播完時間」從第一個到最後一個 speech
PCM release，加上一幀的 20ms；不含模型啟動時間。

| 模式 | 2 秒 PCM 播完時間 | 送端最大間隔 | 接收端最大間隔 | 音訊連續性 |
| --- | ---: | ---: | ---: | --- |
| 原始 1080×1920、PyTorch VAE | 6.52 s | 856 ms | 873 ms | 失敗 |
| 540×960、PyTorch VAE | 6.38 s | 892 ms | 900 ms | 失敗 |
| 540×960、TensorRT VAE | 4.14 s | 519 ms | 525 ms | 失敗 |
| 上述加音訊獨立排程 | 2.00 s | 25 ms | 37 ms | 通過 |

音訊連續性門檻：完整 PCM 送出、送端最大間隔 <60ms、接收端最大間隔
<100ms。資料見 `playback-baseline.json`、`playback-resized.json`、
`playback-vae.json`、`playback-independent.json`。

後續 6 秒獨立排程測試：6.0009 秒播完，送端最大間隔 23.23ms，
接收端 43.77ms，PCM 全部送出；嘴型輸入 queue 過載 18 次，
只丟棄視覺輸入，聲音沒有被拖住。來源：
[playback-independent-long.json](playback-independent-long.json)。

嘴型同步門檻另外計算同一 media_sequence 的送端 audio/video release
牆鐘差，要求至少 5 個配對樣本且 P95 ≤80ms。原始路徑 P95 約 1171ms，
VAE 加速路徑約 682ms；獨立排程沒有足夠配對樣本，因為嘴型結果在
消費時已落後 PCM 而被丟棄。所有模式的 A/V gate 都未通過；
不能將音訊變順暢解讀為嘴型同步已完成。

## 實作與回歸

- PCM 優先 enqueue，再以非阻塞方式提供嘴型輸入；視覺滿載不回壓語音。
- audio track 自行提供 idle silence；renderer 不再產生第二份 PCM。
- 保留 generation fencing；過時嘴型在貼回前丟棄。
- 連線關閉能解除等待中的 PCM producer，feature queue 滿載也可退出。
- 新增實際 renderer 尺寸、嘴型滿載、idle pacing、關閉背壓、VAE fallback 回歸。

驗證結果：

- focused suites：95 passed，12 subtests passed。
- `uv run python scripts/check-integration.py`：通過，含品牌及授權契約。
- `uv run pytest`：457 passed、4 skipped、1 failed。
- `npm test`：84 passed。
- `npm run build`：通過。

唯一 pytest 失敗是既有的原尺寸背景合成時間門檻：
`test_chroma_composite_fits_the_render_frame_budget_on_a_portrait_avatar`。
要求 1080×1920 合成中位數 <30ms，本機單獨重跑為 34.92ms。
本次未修改 `src/scene/service.py` 或放寬該門檻；解析度控制降低實際輸出
成本，但原尺寸測試仍然失敗。記錄見 `pytest.log` 與
`chroma-budget-quiet.log`。

## 實驗設定

- [config-vae.yaml](config-vae.yaml)：沿用 Jetson 設定，加入 960 高度限制與 TensorRT VAE。
- [config-independent.yaml](config-independent.yaml)：再加入音訊獨立排程，A/V 尚未驗收。

兩份設定都只寫在實驗目錄。新欄位預設為 `max_height: 0`、
`vae_engine_path: ""`，原本的串流與獨立排程開關也維持預設停用。
下一步應繼續降低嘴型推理延遲，並完成真人語音與瀏覽器多輪 A/V 驗證，
再決定是否啟用獨立排程。
