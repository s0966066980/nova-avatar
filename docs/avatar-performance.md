<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->

# Nova Avatar 播放效能實驗

新增設定預設停用。2026-09-30 在 Jetson AGX Orin 64GB、50W 模式測試，
使用 `musetalk_1`、FP16 模型、batch 8 與 H264。測量與重播工具位於
`.scratch/avatar-performance/`，完整紀錄見該目錄的 `report.md`。

## 輸出解析度

```yaml
video:
  max_height: 960
```

原始 1080×1920 角色會輸出 540×960。縮放保留比例，不放大素材；
`0` 保留原始大小。嘴型貼回及轉場先使用原始角色座標，再縮圖，
最後進行背景合成與編碼。因此不必重新製作角色，音訊也不受影響。

`video.width`、`video.height` 的既有意義維持原狀；輸出限制使用新的
`max_height`，避免把直式角色拉伸為正方形。

## 可選 TensorRT VAE

```yaml
model:
  musetalk:
    vae_engine_path: /home/oliver/nova-avatar/.scratch/avatar-performance/vae.engine
```

空路徑使用原始 PyTorch VAE。無法載入引擎、缺少 TensorRT、輸入超出
引擎 profile 或執行失敗時，會記錄原因並回退原始 decoder。
encoding 與模型參數仍由 MuseTalk 負責，口型融合流程維持原有行為。

引擎契約：CUDA FP16 `latents`，形狀 `[batch, 4, 32, 32]`；
FP16 `decoded`，形狀 `[batch, 3, 256, 256]`。引擎內包含 latent scaling
及 VAE decode，輸出為未正規化的 decoder samples；adapter 完成原有的
range、rounding 及 BGR 轉換。不要直接套用其他輸出契約的 VAE 引擎。

本機建立的引擎 profile 支援 batch 1–8。引擎需配合 GPU、TensorRT
版本及模型權重重新建立；`vae_engine_path` 不提供模型或權重授權。

## 音訊獨立排程實驗

```yaml
reply_streaming:
  enabled: true
  decoupled_audio_clock: true
```

PCM 先送入有背壓的 WebRTC audio queue，再提供給嘴型輸入。
嘴型 queue 滿載時只丟棄過時的視覺輸入，不丟棄已接受的語音 PCM。
idle silence 由 audio track 自行排程，renderer 不再送第二份音訊。
generation fencing 保留；關閉連線也會解除等待中的 PCM producer。

此模式的 2 秒與 6 秒本機 WebRTC 連續音測試已通過音訊連續性門檻，
但嘴型同步驗收失敗。GPU 推理仍慢於即時需求，renderer 會丟棄落後
音訊超過約 80ms 的嘴型結果；觀察到的流暢聲音不代表嘴型已同步。
目前應只在隔離實驗中啟用，尚未通過 ADR-0007 要求的完整 A/V 驗收。

## 重播

在專案根目錄使用既有 Jetson 設定、角色素材與模型。工具自行建立一對
本機 WebRTC peers，不必啟動或重新啟動現有 server：

```bash
.venv/bin/python .scratch/avatar-performance/compare_vae.py
.venv/bin/python .scratch/avatar-performance/playback_probe.py \
  --height 960 --engine .scratch/avatar-performance/vae.engine \
  --independent --seconds 6 \
  --output .scratch/avatar-performance/playback-independent-long.json
```

輸入為確定性的連續音，不含 LLM、ASR 或遠端 TTS 延遲，也不代替真人
語音聆聽、多輪插話、網路抖動與瀏覽器長時間測試。

完整文字已備妥的真實 Edge TTS 對照可使用 `--speech`：

```bash
.venv/bin/python .scratch/avatar-performance/playback_probe.py \
  --speech --height 960 --engine .scratch/avatar-performance/vae.engine \
  --independent --output .scratch/reply-latency/speech-independent.json
```

這次相同 9.08 秒語音的原始耦合路徑花 34.51 秒播完，獨立音訊約
9.08 秒播完，PCM 全數送出。TTS 共用事件迴圈的 PCM 背壓也已修正；
單獨修正 TTS 而保留音訊與嘴型耦合，仍需約 30.81 秒播完。
嘴型同步仍失敗，首音 P95 目標尚未通過。完整數值及隔離服務啟動方法
見 [.scratch/reply-latency/report.md](../.scratch/reply-latency/report.md)。
