<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->

# 正式朗讀路徑診斷與修正

2026-10-02，Jetson AGX Orin。同一完整固定回答，正式 `/offer` →
`/human type=echo` → Edge TTS → MuseTalk → H.264 → aiortc 接收解碼。
測試沒有啟動或呼叫 LLM；最終驗證時未有本機 llama-server 或另一個
Nova Avatar 服務。兩次重現均用已驗證的 720p 加速模型。

## 發現

- 一般 `config.yaml`／`config_jetson.yaml` 沒有選用 TensorRT UNet、
  輕量解碼或輸出高度限制，仍有上輪確認的完整 VAE 瓶頸。
- 單純選擇 realtime YAML 仍會被保存的 llama.cpp 偏好覆蓋。重現
  `load_config('config/config_jetson_realtime.yaml')` 得到 llamacpp，
  所以新入口必須自動停用該程序的 runtime overrides。
- 舊 `echo` 直接 `put_msg_txt(text)`，未帶輪次與 media sequence，
  無法量測或套用嘴型落後的序號控制，也未在 TTS 起音前關閉收音。
- 嘴型 inference 將安靜 PCM 轉成 idle 嘴型。`_is_unscoped_idle_result`
  只檢查沒有 turn_id，誤把沒有完整 envelope 的 TTS 安靜片段與
  結尾當成可丟棄的待機資料。舊朗讀合成 **10.30s，僅送出9.20s**，
  結尾事件遺失。現在只有 `eventpoint is None` 才屬於可丟的待機。
- `vad.enabled=false` 原本仍載入 Silero／ASR。現在會跳過語音輸入
  暖機並維持收音關閉；一般啟用 VAD 的對話設定沿用原路徑。

## 改動

`start_read_aloud_turn` 將固定文字直接送到 TTS，帶正常 generation
fence、fragment sequence、media sequence，不執行 LLM。起音前
關閉收音；重送有 interrupt 時取消舊輪次；TTS worker 失敗由服務
event loop 接收；朗讀結束也發出已播文字提交事件。
朗讀前端檢查 HTTP 狀態與 `code=-1`，避免請求失敗仍顯示已送出。

`bash scripts/start-jetson.sh --realtime` 明確選用加速朗讀設定，
自動忽略保存的覆蓋設定並停用 RAGFlow。720p、batch8、25fps、
TensorRT UNet + TAESD；不載入 LLM、VAD 或 ASR。TAESD 會略柔化
牙齒與唇部細節。此 profile 只供朗讀；一般對話以原啟動指令恢復。
模型初始化／執行回退仍可能失去即時效能，實測有確認兩個 adapter
實際載入且沒有回退。沒有放寬驗收門檻或變更保存的偏好。

## 結果

| 項目 | 舊正式朗讀 | 修正後正式朗讀 |
| --- | ---: | ---: |
| TTS PCM 長度 | 10.30s | 10.30s |
| 送出 PCM 長度 | 9.20s | 10.30s |
| 首包到末包的播放時間 | 9.659s（不完整） | 10.2998s |
| 最大標記音訊間隔 | 75.98ms | 27.77ms |
| 文字到首音 | 0.958s（不完整） | 1.276s |
| PCM 到首音 | 0.617s | 0.582s |
| 嘴型對應影格覆蓋率 | 無配對 metadata，不能評估 | 98.25% |
| A/V 釋放偏差 P95 | 無配對 metadata，不能評估 | 52.38ms |
| 全部連續性與同步驗收 | 失敗 | 通過 |

[舊路徑數據](echo-before.json)、[修正後數據](echo-after.json)。
第一版測試等待結尾事件而逾時；改用實際 PCM 完整性與 TTS pending
完成判定後，保留了丟失 PCM 的失敗數據。初次逾時紀錄為
`echo-before.log`，修正測試觀測後的失敗紀錄為 `echo-before-rerun.log`。
舊測試有背景索引 CPU 競爭，因此前後最大間隔不能視為完全控制
資源下的單變量差異；PCM 丟棄另以確定性的佇列測試確認。
最終效能測試暫停本 Codex 的 codebase-memory 索引程序，以 EXIT
trap 自動恢復，已確認恢復，沒有停止使用者服務或瀏覽器。

三個回歸先失敗再通過：朗讀起音前收音與 envelope、停用語音輸入
不載入 ASR，以及啟動入口忽略保存的 LLM 設定。另有兩個 PCM
回歸案例先失敗再通過：空 envelope 的安靜片段與結尾事件均不得
在 idle backlog 清理時丟棄。
聚焦檢查：97 通過、12 subtests 通過。

重跑：

```bash
NOVA_AVATAR_RUNTIME_OVERRIDES_ENABLED=0 uv run python \
  .scratch/read-aloud/playback.py \
  --output .scratch/read-aloud/echo-playback.json
```

接收解碼已包含，瀏覽器顯示、喇叭與外部網路尚未納入此驗收。
實測口形推理仍需選用加速設定，不能宣稱原始完整 VAE 已即時。

## 全套驗證

紀錄位於 `integration.log`、`pytest-full.log`、`npm-test.log`、
`npm-build.log`，退出碼見 `validation-status.txt`。

- 整合、品牌與授權檢查：通過。
- Python：490 通過、4 略過、1 失敗。失敗是原有全解析度綠幕
  合成效能測試，1920×1080 中位數 35.95ms，門檻 30ms；上輪已有
  相同失敗。本輪沒有改該算法或放寬門檻，加速朗讀使用 720p。
- 前端：84 通過；正式 build 通過，保留既有 bundle 大小提示。
- `git diff --check`、啟動腳本 `bash -n`：通過。
