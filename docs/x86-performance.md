<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->

# x86 即時數位人效能優化

本次將 Jetson 分支的通用效能改動移植到 x86 即時 MuseTalk。預設使用
原有解析度與完整 VAE；TensorRT 與輸出縮圖由部署者另行選用。

## 首音延遲改善（2026-10-30）

目前預設組合：llama.cpp 的 Gemma 4 E2B（全部層數放進 GPU，Qwen3.5-9B 可選）、
faster-whisper small（語音輪次只在中英文間偵測、beam 1、記憶體直傳）、Edge TTS
（僅供開發）、MuseTalk。路由、檢索與主回答同時開始，檢索上限 0.7 s；MuseTalk
待機節流可被回覆音訊喚醒，每輪第一批用啟動批次。

RTX 4090、舞台 WebRTC 量測 3 輪 96 句（`scripts/measure_first_audio.py`），P50／P95。
感知首音是人聲實際結束到伺服器送出第一個可聽回覆音訊幀；「用戶端收到」另含約
0.10 s 下行與量測工具的抖動緩衝，基準線只有這個定義：

| 類別 | 基準線（用戶端收到） | 最終（用戶端收到） | 最終感知首音 |
| --- | ---: | ---: | ---: |
| 一般 | 4.09／4.43 s | 2.10／2.34 s | 2.00／2.22 s |
| RAG | 3.93／4.22 s | 2.10／2.38 s | 2.00／2.28 s |
| 交接 | 2.48／2.69 s | 1.73／2.30 s | 1.63／2.20 s |

一般輪次 P50 組成：VAD 拖尾 0.08＋靜音等待 0.32＋上行 0.09＋辨識 0.07＋檢索等待
0.56＋首片段 0.42＋片段到送出 0.36＋Edge 開頭無聲段 0.10 s。基準線（Qwen3.5-9B、
Whisper beam 5、路由與檢索串行）的辨識為 0.41、主回答前 1.29、首片段 0.93、片段
到送出 0.62 s。起訖定義、對照規格目標與下一步見
[目前專案基線](project-status.md#首音延遲實測2026-10-30)。

本機 TTS 尚未納入上表：與 MuseTalk、E2B 共用 GPU 時，BreezyVoice 第一個片段
P50／P95 2.48／2.94 s，Fun-CosyVoice3 1.77／1.89 s（Edge TTS 首段 PCM 約 0.16 s）。
E2B＋MuseTalk 共占 18.0 GB，再載 BreezyVoice 峰值 23.9／24.5 GB。

以下 10 月 15–16 日的實測使用 Qwen3.5 9B 與 FunASR，首音從「伺服器接受 Prompt」
起算，不能與上表直接比較。

## 預設生效的改善

- 綠幕距離變換與去綠邊只計算人物可見範圍，保留其外的綠幕邊界；
  改用 OpenCV 掃描待處理像素。
- 有 PCM 待處理時，不再因視訊佇列滿載額外節流。起音前替換未標記的
  待機 lookahead，為首批語音保留足夠窗口；短句完成後仍可排出。
- TTS MP3 解碼與可能阻塞的 PCM 入列在工作執行緒執行，共用網路事件
  迴圈可繼續處理下一片段。預取保持最多下一段，並保留既有連線重用、
  endpoint failover 與限流重試。
- 前一片 PCM 全數入列後，下一片可接續進入同一有界 FIFO；入列不表示
  已播，片段提交、字幕與對話歷史仍依實際輸出音訊。緩存排空前保持
  gate，避免新 PCM 超車；取消會丟棄尚未送出的緩存。
- 音訊缺資料時維持主時鐘，只在下一封包期限前等待剩餘時間；視訊
  PTS 反映實際釋放時間，避免微小排程誤差累積成大幅跳幀。
- 口語通道的完整結束標記可釋放尚未帶句尾標點的口語摘要，無須等待
  看板 JSON；部分標記與原始結構化資料不交給 TTS。
- 啟動時預熱 Edge 的 PCM 解碼及本機 llama.cpp 的實際 Prompt 前綴。
  預熱不播放、不寫對話歷史；外部 LLM provider 不執行此預熱。
  預熱失敗記錄警告，保留原有請求恢復流程。
- 純觀看會話不準備 VAD／STT；有上行麥克風時平行準備與協商，準備
  完成前保持收音關閉。暫停收音時仍消費上行音軌，但略過重採樣。

原有的嘴型連續控制、音訊主時鐘、輪次隔離、舞台訪客重置及有期限的
後端關閉流程沿用。獨立 PCM 實驗開關維持預設關閉。

## 啟動與第一輪音畫同步修正（2026-10-16）

本次檢查以工作區既有的 x86 優化為基礎，另修正三個實際缺口：

- 控制台原先每次收到 `ontrack` 都重新設定 `video.srcObject`。音軌與
  視訊軌分開抵達時會重複接管播放器；現在與獨立舞台一樣，只綁定一次
  `MediaStream`，後續只加入新軌。動態回歸測試涵蓋分開及重複到達的軌。
- MuseTalk 的 `flush_talk()` 原先清除特徵上下文，卻沒有補回左、右窗口。
  下一輪因此先等待更多 PCM，且特徵中心可能與配對 PCM 錯位。現在以
  純靜音重建窗口，不消費新輪次語音；同時以 context epoch 丟棄清除前
  尚在 Whisper 執行或等待入列的批次，避免舊工作覆寫新上下文。
- 原本的模型預熱只用假特徵跑一次完整 batch 的 UNet／VAE。現在先走
  真正的 Whisper 特徵抽取，再分別預熱首批 `min(batch_size, 4)` 與穩態
  batch 的 UNet／完整 VAE。預熱結果不進入語音、字幕或對話歷史。

本機 RTX 4090／Torch 2.5.0+cu124 的獨立 Whisper 微基準，使用
11,520 個 16 kHz 靜音樣本，GPU 計時前後同步：第一次 **287.257 ms**，
接續五次中位數 **5.399 ms**。這表示本機可把約 282 ms 的特徵抽取冷啟動
成本移到服務就緒前；它不是整輪首音降低 282 ms 的保證，也不代表穩態
推理加速。模型載入及預熱本身仍增加啟動時間。

### Jetson Orin 預熱可移植性

比對的本機遠端追蹤版本為 `origin/jetson-orin` 的 `46db729`。

| 預熱做法 | x86 判斷 |
| --- | --- |
| Edge 網路與 MP3→PCM 解碼、與模型載入重疊 | 可沿用，工作區已具備；遠端限流或握手失敗仍可能讓預熱失敗。 |
| 本機 llama.cpp 使用實際角色／回覆協定 Prompt | 可沿用，工作區已具備；主要暖 Prompt cache，不改善遠端 TTS 或音畫配對。 |
| MuseTalk 單次完整 batch 的 UNet／VAE | 原主分支已具備，單純搬移沒有新增效益；本次補上 Whisper 與首批尺寸。 |
| VAD／STT 在 WebRTC 準備期間載入 | 可共用；後續實作再於 x86 啟動時補上 STT 實際推理與 FunASR 轉換預熱，見下節。 |
| 任一回覆預熱失敗就阻擋 health／offer | 未直接移植：Orin 的嚴格閘門沒有在此啟動路徑自動重試；暫時的 Edge 失敗可能讓本來可恢復的會話一直不能開始。 |
| Orin 的 TensorRT engine／硬體調校值 | 不能直接使用；需要在目標 x86 GPU 重建與量測。 |

因此，預熱能改善 x86 的第一輪冷啟動，但嘴型配對仍必須由上下文與
播放時序修正；不能以加長音訊緩衝取代同步修正。

語音實測工具新增 `--client-role`，可分別覆蓋控制台與舞台的後端會話：

```bash
uv run python scripts/run_voice_soak.py --client-role stage --turns 6 \
  --interrupt-every 3 --llm-interrupt-every 5 --reconnect-every 4 \
  --output /tmp/nova-stage-startup.json
uv run python scripts/run_voice_soak.py --client-role console --turns 6 \
  --interrupt-every 3 --llm-interrupt-every 5 --reconnect-every 4 \
  --output /tmp/nova-console-startup.json
```

這是實際 WebRTC／STT／LLM／TTS 會話驗證，不包含瀏覽器喇叭播放與
人物口型的人工視聽驗收。少於 50 輪的報告仍會將完整 soak gate 標成
未通過；不可把這個短測當成 50 輪 SLO 驗收。

2026-10-16 在同一台 RTX 4090，以目前角色、背景、TensorRT 引擎、
Qwen3.5 9B、FunASR 與 Edge TTS 依序短測；每種角色六輪，包含兩次
出聲後插話、一次 LLM 階段插話及一次重連。每組有五輪實際出聲。

| 指標 | 舞台 | 控制台 |
| --- | ---: | ---: |
| 首音 P50 | 1.099 s | 1.132 s |
| 首音 P95 | 1.743 s | 1.404 s |
| 後端配對音畫時間戳偏移 P95 | 30.925 ms | 21.719 ms |
| 插話停止 P95 | 0.328 ms | 2.471 ms |
| 恢復收音 P95 | 301.776 ms | 302.981 ms |
| 已取消輪次的外洩事件 | 0 | 0 |

兩組除了「至少 50 輪」之外的報告檢查均通過；配對時間戳不是瀏覽器
端視聽延遲或人物發音準確度。測試環境沒有可用的瀏覽器控制連線，
前端以動態 `ontrack` 回歸測試驗證，尚未做實際瀏覽器視聽驗收。

修正前後的單次冷啟動首音分別約 1.530 s、1.518 s，差異不足以支持
整輪加速的結論；首輪 STT 成本、生成長度及遠端 TTS 波動仍存在。
本次也遇到 Edge 預熱握手失敗與測試語音合成 HTTP 429；語音測試在
退避後完成，沒有據此調高正式服務的重試或啟用嚴格預熱閘門。

原始純量報告位於
[啟動音畫同步測試產物](../.scratch/startup-av-sync/)，不含錄音、
轉寫或對話內容。完整驗證為 Python **527 passed、3 skipped**，
前端 **96 passed**，integration／品牌檢查及前端建置通過。

## 啟用 Orin 預熱流程於 x86

`app.prewarm: true` 現在預設啟用完整預熱。Edge 與本機模型載入重疊執行，
LLM 沿用 Orin 的實際 Prompt 短生成流程，會完成這次有期限的生成，
不再於第一個協定標記就取消。MuseTalk 延續前節的 Whisper、首批與
穩態 UNet／VAE 預熱。所有預熱輸出都不進入會話、字幕或對話歷史。

另外補上 STT 真正的推理預熱：用一秒合成靜音跑所選本機辨識器，
FunASR 同時初始化設定的文字轉換字典。成功結果在引擎內快取，控制台
與舞台共用時不會重複推理；預熱失敗則保留下一次會話準備時重試。
VAD 亦在啟動時載入與試跑，測試用的 VAD 狀態隨即釋放。

Edge 預熱最多兩次，使用同一個總期限，握手被拒絕時切換 endpoint，
HTTP 429 時退避後再試。`/health` 新增 `prewarm`，分別回報 Avatar、
Edge、本機 LLM 與語音輸入的成功狀態；`null` 表示未選用或已關閉。
遠端預熱失敗仍保留正式回覆的恢復流程，服務可用性與預熱結果分開回報。

僅在目前程序切換預熱的對照方式如下，不會改寫管理者儲存的設定：

```bash
NOVA_AVATAR_PREWARM_ENABLED=0 uv run python -m src.server.app
NOVA_AVATAR_PREWARM_ENABLED=1 uv run python -m src.server.app
```

冷啟動比較使用新增工具，要求後端與所選 llama-server 都尚未啟動。
工具只啟停自己建立的程序，每次用全新的後端與 llama-server，交錯執行
「關／開、開／關」。同一組試驗重用記憶體裡的固定合成語音，產物只
保存純量，不保存音訊或逐字內容。這是程序冷啟動，沒有清除作業系統
檔案快取；llama-server 自己的啟動行為在兩組保持一致。

```bash
uv run python scripts/benchmark-prewarm.py --client-role stage \
  --output .scratch/startup-av-sync/orin-prewarm-ab-stage.json
uv run python scripts/benchmark-prewarm.py --client-role console \
  --output .scratch/startup-av-sync/orin-prewarm-ab-console.json
```

報告同時記錄程序啟動至 ready、WebRTC 連線至 listening、首音延遲及
STT 階段時間。預熱會把工作移到服務開放前，首音改善必須連同增加的
啟動成本一起看，不能把前節的模型微基準當成整輪改善倍率。

### RTX 4090 冷啟動 A/B 結果（2026-10-16）

舞台與控制台各跑四個全新程序，順序為關、開、開、關；每個角色每組
兩次，以下為中位數。沿用目前的 MuseTalk 角色、完整解析度、背景、
TensorRT、Qwen3.5 9B、FunASR 與臺灣 Edge 聲音。這組量測比較應用
預熱整體開／關；前節六輪短測使用較早的部分預熱設定，樣本不混合計算。

| 指標 | 舞台：關 → 開 | 控制台：關 → 開 |
| --- | ---: | ---: |
| 首音延遲 | 2.273 → 1.074 s | 2.239 → 1.131 s |
| 本次首音降低比例 | 52.73% | 49.48% |
| STT 階段 | 410.705 → 48.016 ms | 382.298 → 54.684 ms |
| 程序啟動至 ready | 18.431 → 23.196 s | 17.930 → 22.570 s |
| WebRTC 連線至 listening | 7.820 → 3.460 s | 7.667 → 3.778 s |

四次開啟預熱的 Avatar、Edge、LLM 與語音輸入狀態均為成功。八次
試驗都實際收到非靜音音訊及視訊；後端配對音畫時間戳偏移最大值為
舞台 **22.956 ms**、控制台 **22.100 ms**。沒有把預熱回答送入訪客會話。

本次結果支持完整預熱能降低這台 x86 主機的首輪等待；啟動本身則多約
4.6–4.8 秒，連線準備少約 3.9–4.4 秒。每組只有兩次，遠端 TTS 與模型
回覆仍會波動，這不是 P95、50 輪 soak 或瀏覽器視聽驗收。

原始報告：
[舞台 A/B](../.scratch/startup-av-sync/orin-prewarm-ab-stage.json)、
[控制台 A/B](../.scratch/startup-av-sync/orin-prewarm-ab-console.json)。
每次試驗結束都已正常關閉工具自行啟動的後端及 llama-server。
本次完整驗證為 Python **538 passed、3 skipped**、前端 **96 passed**，
整合／品牌檢查與前端建置通過。

## CPU 合成對照

```bash
uv run python scripts/benchmark-compositor.py --output logs/x86-compositor.json
```

工具使用既有測試的直式人物橢圓樣本，交替量測目前實作與固定 Git
基準 `73e7b74`，各暖機三次並量測二十次，同時檢查輸出像素完全一致。
`--baseline-ref` 僅接受部署者信任的本機版本，工具會載入該版本的合成
程式。這是 CPU 合成微基準，不包含嘴型、編碼、LLM 或瀏覽器播放。
端到端速度仍需在目標角色、背景與併發負載下比較。

2026-10-15 本機 x86、OpenCV 20 threads 的結果如下；兩種尺寸的
樣本像素均與基準完全一致：

| 合成尺寸 | 基準中位數 | 優化後中位數 | 合成階段加速 |
| --- | ---: | ---: | ---: |
| 1080×1920 | 12.52 ms | 8.82 ms | 1.42× |
| 720×1280 | 5.07 ms | 3.48 ms | 1.46× |

## 可選完整模型 TensorRT

`inference_optimization.py` 與 `vae_acceleration.py` 使用目前 MuseTalk
權重，沒有引入近似解碼器。需要 NVIDIA CUDA GPU；引擎必須在目標
GPU、對應 TensorRT runtime 與目前模型權重上重建。Orin engine 不可
直接搬到 RTX 4090。adapter 保留原模型供載入／執行失敗時回退，也會
額外占用顯存，需與本機 LLM 共跑驗證。

安裝、建置、啟用與重驗的完整步驟見
[TensorRT 安裝與驗證](installation.md#tensorrt-安裝與驗證)。一般使用：

```bash
bash scripts/setup-tensorrt.sh
uv run python scripts/verify-musetalk-tensorrt.py
```

套件固定為 `tensorrt-cu12==10.16.1.11`、`onnx==1.17.0`。安裝器使用
專案 `.venv`，只有通過數值驗證、目前 batch 已量得加速且引擎 SHA-256
一致時才寫入本機 runtime overrides，保留其他設定並備份原檔。普通
`start-all.sh`／`start-backend.sh` 啟動即可套用，不需臨時 `--with` 環境。

### RTX 4090 實測：2026-10-15

環境為 RTX 4090 24 GB、driver 580.178.04、Torch 2.5.0+cu124、
CUDA 12.4、TensorRT 10.16.1.11。每個 batch／實作暖機五次，交替量測
二十次，GPU 呼叫前後同步，以中位數計算加速倍率。

元件比較使用固定種子的隨機輸入，完整 VAE 包含轉為 CPU BGR 像素：

| 元件／batch | PyTorch | TensorRT | 加速 | 數值品質 |
| --- | ---: | ---: | ---: | --- |
| UNet／1 | 11.03 ms | 7.06 ms | 1.56× | L2 0.199% |
| UNet／4 | 15.94 ms | 8.46 ms | 1.89× | L2 0.195% |
| UNet／8 | 21.88 ms | 10.31 ms | 2.12× | L2 0.197% |
| 完整 VAE／1 | 11.02 ms | 4.61 ms | 2.39× | PSNR 54.85 dB |
| 完整 VAE／4 | 37.51 ms | 13.43 ms | 2.79× | PSNR 54.75 dB |
| 完整 VAE／8 | 76.19 ms | 27.46 ms | 2.77× | PSNR 54.74 dB |

正式載入流程驗證使用目前角色 `musetalk_1` 的真實 latent 快取，輸入
16 kHz 固定合成音訊，經 Whisper 取得特徵後比較 UNet＋完整 VAE＋CPU
像素交付。Whisper 特徵預先計算，未包含在下表計時內；兩個 adapter
均實際執行 TensorRT，沒有回退。產生的左右對照圖亦已目視檢查。

| batch | PyTorch 合併推論 | TensorRT 合併推論 | 加速 | 輸出 PSNR |
| --- | ---: | ---: | ---: | ---: |
| 1 | 18.76 ms | 11.48 ms | 1.63× | 57.26 dB |
| 4 | 52.63 ms | 21.93 ms | 2.40× | 57.65 dB |
| 8 | 96.19 ms | 38.49 ms | 2.50× | 57.72 dB |

因此本機 batch 8 的上述模型階段時間降低約 **60%**，加速約 **2.50×**。
這不是整體 WebRTC FPS、首音延遲或 LLM 加速倍率；合成、編碼、網路
與瀏覽器播放仍須依實際場域負載驗證。測試保留完整 VAE 與原解析度。

實際後端亦已啟動並回報 `ready: true`、`model_ready: true`，同時載入
兩個 TensorRT 引擎與本機 Qwen3.5 9B。健康檢查時總顯存約 18.4 GB
（包含桌面等既有程序），未超過本機 24 GB；測試結束已停止驗證服務。
本機 WebRTC loopback 另送入三秒合成 PCM，成功收到 396 個音訊封包
與 186 幀 1080×1920 視訊，其中 151 個音訊封包非靜音，接收 PTS
遞增且連線正常關閉，後端無 TensorRT 回退。這是連通與實際輸出檢查，
不涵蓋真實麥克風／STT／LLM／TTS 回合延遲或長時間穩態 FPS。

原始報告與圖在本機 `.local/tensorrt/musetalk/comparison.json`、
`avatar-verification.json` 和 `avatar-batch*-comparison.png`；引擎與測試
產物均不加入 Git。UNet 相對 L2 門檻為 2%，VAE／合併畫面 PSNR 門檻
為 35 dB。更換權重、GPU 或 TensorRT 後需重建與重測。

## 可選輸出尺寸

```yaml
video:
  max_height: 1280
```

這會讓 1080×1920 角色輸出為 720×1280；`0` 保持素材尺寸。只縮小、
不放大、不拉伸，嘴型貼回與轉場使用原始座標，接著才縮圖、合成與
編碼。此選項減少輸出像素，也降低畫面解析度；不會加速 UNet／VAE
本身，或提高模型產生的嘴部細節。

## 驗收

```bash
uv run python scripts/check-integration.py
uv run pytest
cd web
npm test
npm run build
```

首音延遲以 `scripts/measure_first_audio.py` 量測（舞台身分、真實 WebRTC，
需先關閉舞台頁），報告列出感知首音、首音與伺服器接受 Prompt 起算三種起點及
各段時間。

目標機 A/B 應固定角色、解析度、背景、模型、聲音與問題集，分別記錄
首音延遲 P50／P95、標記 PCM 完整性與釋放間隔、嘴型配對／凍結、
CPU／GPU 負載及顯存。合成或模型的微基準加速不能直接當成整體 FPS
或首音改善倍率；收音、辨識、生成與播放的重疊時間也不能直接相加。
