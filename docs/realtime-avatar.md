<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->

# Jetson 數字人即時生成測試

`config/config_jetson_realtime.yaml` 是單一會話的固定回答診斷設定：
MuseTalk、batch 8、25fps、直式 720×1280、FP16 TensorRT UNet，以及本機 TAESD
輕量解碼器。原始設定檔仍使用原有解碼器。

TAESD 是近似解碼，牙齒與唇部細節會略柔化。原 VAE 仍負責素材編碼；
空的 `tiny_vae_path` 保留原 VAE。UNet engine 初始化或執行失敗會回退
PyTorch；輕量解碼失敗會回退原 VAE。回退保留功能，但可能無法維持即時速度。
TAESD 的模型、MIT 授權及作者資料見 [第三方聲明](../THIRD_PARTY_NOTICES.md)。

## 本機檔案

此工作站已備妥以下檔案，模型及 engine 不加入 Git：

- `.local/jetson/taesd/`：`madebyollin/taesd`，revision
  `614f76814bbe30edbe2e627ace1c2234c81a2c0e`。
- `.local/jetson/musetalk-unet-fp16.engine`：由目前 MuseTalk UNet
  在 Orin 上建置；零 diffusion timestep，batch 1–8，輸入 FP16
  `sample [N,8,32,32]`、`encoder_hidden_states [N,50,384]`，
  輸出 `latent [N,4,32,32]`。

Engine 需與目前模型、GPU 及 TensorRT 相容；換機或更新模型後重新建置。
匯出與建置實驗留在 `.scratch/realtime-avatar/`，包括數值比較結果。
需要下載 TAESD 時可使用：

```bash
uvx --from huggingface_hub hf download madebyollin/taesd \
  config.json diffusion_pytorch_model.safetensors README.md \
  --revision 614f76814bbe30edbe2e627ace1c2234c81a2c0e \
  --local-dir .local/jetson/taesd
```

## 不載入 LLM 的實測

固定 PCM 重播會跑 Whisper 音訊特徵、MuseTalk 推理、貼臉、背景合成、
H.264 編碼及真實 aiortc WebRTC 發送／接收解碼。它不執行 ASR、LLM
或遠端 TTS，因此能隔離數字人本身的瓶頸。

```bash
NOVA_AVATAR_RUNTIME_OVERRIDES_ENABLED=0 uv run python \
  .scratch/realtime-avatar/playback.py \
  --config config/config_jetson_realtime.yaml --production-model \
  --height 1280 \
  --pcm-file .scratch/fixed-reply-diagnosis/fixed-reply.npz \
  --repeat 3 --profile \
  --output .scratch/realtime-avatar/replay.json
```

沒有 PCM fixture 時，加上 `--speech --single-reply` 取代 `--pcm-file`
與 `--repeat`，會直接合成完整固定回答，仍不呼叫 LLM。
單用 `--speech` 會測三個獨立 TTS 片段，確認片段銜接。

`NOVA_AVATAR_RUNTIME_OVERRIDES_ENABLED=0` 只在該程序忽略控制台保存的
設定。控制台可能保存 `llamacpp` provider，否則它會蓋過診斷 YAML 並
在服務啟動時載入 LLM。此開關不修改已保存的偏好。

## 在網頁連線後使用固定回答

```bash
bash scripts/start-jetson.sh --realtime
```

此入口自動忽略控制台保存的覆蓋設定，選用加速 profile；不啟動
LLM 或 RAGFlow。profile 停用語音輸入，因此連線也不載入 VAD／ASR，
只使用網頁的「朗讀模式」。啟動前停止原服務，避免兩個 renderer
競爭同一顆 GPU。`bash scripts/start-jetson.sh` 恢復原對話設定。

完成數字人連線後，使用實際 `sessionid` 呼叫 `/human`，設定
`type: "echo"`、`text` 為固定回答。`echo` 直接進 TTS，不經過 LLM。
朗讀現在同樣帶入輪次與 media sequence，起音前暫停收音，重送時
取消舊朗讀，並保留合成語音的安靜片段及結尾 PCM。
此診斷 profile 的 LLM endpoint 指向未提供模型的本機 port 9；一般
`chat` 不適用於此 profile。回到原設定即可恢復正常對話。

## 驗收與限制

播放時間應接近 PCM 原長度、完整送出全部 PCM，最大標記音訊間隔
小於 60ms；至少 95% 的對應嘴型影格需送出，首個對應 A/V 釋放時間
偏差 P95 不超過 80ms。第一包 PCM 就緒至首音目標不超過一秒。
嘴型配對以 fragment sequence 和 media sequence 為鍵，重複影格不
重複計分。遠端 TTS 的文字到首音時間另行記錄。

這是 Orin MODE_50W、單會話、本機 WebRTC 的測試範圍；測試包含接收
解碼，但不包含瀏覽器顯示、實際喇叭、外部網路、VAD 或對話 ASR。
本輪未載入 LLM，不代表加入 LLM 共跑後仍維持相同效能。
完整結果見 [診斷報告](../.scratch/realtime-avatar/report.md)。

實際 HTTP `/offer` → `/human` 朗讀與 WebRTC 接收解碼的重現：

```bash
NOVA_AVATAR_RUNTIME_OVERRIDES_ENABLED=0 uv run python \
  .scratch/read-aloud/playback.py \
  --output .scratch/read-aloud/echo-playback.json
```

此重現使用正式服務路由、會話柵欄與真實模型；不經過 LLM。
瀏覽器顯示與喇叭仍需在同一加速設定下確認。
