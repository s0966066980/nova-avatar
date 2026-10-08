<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->

# Nova Avatar 回覆斷續修復與驗證

2026-09-30。LLM 完整文字已備妥時，主要瓶頸仍在嘴型推論對音訊的
背壓；另外確認共用 TTS 網路事件迴圈會被 PCM 入列阻塞。
以下是本機真實 Edge TTS、MuseTalk、H264 WebRTC 接收解碼的隔離對照，
不包含 LLM、VAD、ASR，也不是瀏覽器實際喇叭的感知首音驗收。

## 完整文字重播

預先提供相同三句公開測試文字，不需等待 LLM 生成。實際 TTS PCM 共
9.08 秒，三組皆完整送出。GPU 實驗依序執行，每組一次。

| 模式 | 首 PCM release | 9.08 秒 PCM 播完 | 最大 PCM release 間隔 | 連續性 |
| --- | ---: | ---: | ---: | --- |
| 原始 TTS、耦合音訊、原尺寸、PyTorch VAE | 1.947 s | 34.509 s | 1341 ms | 失敗 |
| 修正 TTS、仍耦合音訊 | 1.962 s | 30.812 s | 1249 ms | 失敗 |
| 修正 TTS、獨立音訊、540×960、TensorRT VAE | 0.411 s | 9.081 s | 25.2 ms | 通過 |

資料：[speech-baseline.json](speech-baseline.json)、
[speech-fixed-coupled.json](speech-fixed-coupled.json)、
[speech-independent.json](speech-independent.json)。
門檻為來源 PCM 全數送出、最後片段完成且送端 tagged PCM 最大間隔 <60ms。
真實語音含自然停頓，接收端 active-voice 間隔不能直接當作處理停頓。
本次不是獨立音訊單一因素的完整 factorial A/B；前次連續音 A/B 已
另外分離解析度、VAE 與獨立排程的效果，見
[前次報告](../avatar-performance/report.md)。

## 實作

- TTS MP3 解碼與可能阻塞的 PCM 入列改用工作執行緒，讓共用 asyncio
  loop 持續處理後續 Edge 請求。PCM 可用時即可觸發預取，播放提交仍
  依原有 media fencing 與片段順序。
- 獨立音訊使用既有 opt-in 開關；慢速嘴型輸入不回壓已接受的 PCM。
  對過載僅丟棄視覺輸入。解析度與 TensorRT VAE 同樣保持 opt-in。
- 服務就緒前完成 Edge 實際 PCM 解碼預熱，以及目前本機 LLM profile／
  回覆協定的 prompt prefill；預熱不寫歷史、不發送到舞台。失敗時
  `/health.ready` 為 false，`/offer` 回覆 503；需排除依賴故障後重啟。
- 新增 VAD endpoint wait、LLM 首可朗讀文字及 TTS PCM 可用量測，
  區分 PCM 已產生與 PCM 能入列，缺測保持 null。
- 統一新建 LLM 引擎與控制台更新的 token budget，取消新建時額外
  強制至少 1024 tokens。短首句規則沿用可編輯規則介面，不覆寫既有
  自訂規則；隔離實驗附加短首句策略。
- 完整口語頻道結束時立即送出剩餘語意片段，不再因缺少句尾標點而
  等待整份看板 JSON。切分處是完整協定邊界，分段標記及看板資料
  仍不進語音；回歸同時檢查部分標記不能提前觸發。

## 品質與部署界線

獨立音訊測試的嘴型配對樣本為 0，A/V gate 失敗；仍有晚到嘴型及
視覺輸入過載。原始耦合路徑的 A/V 同樣未達門檻。
不能把流暢聲音當作嘴型同步已修好。就緒後感知首音 P95 ≤2 秒尚未
取得足夠端到端樣本，這仍是目標。

隔離啟動：`uv run python .scratch/reply-latency/run_isolated.py`。
它讀取目前有效設定，再使用後端 8011、llama-server 8091、960 高度、
TensorRT 與獨立音訊；使用私有 override 路徑，避免全域覆寫把實驗
開關蓋回 false。原本 8010 與全域 runtime overrides 保持原狀。
產生的有效設定含目前私有設定，已忽略 Git 並設為 0600，不供對外分享。

## 驗證

背壓阻塞後續 TTS 網路請求的回歸已先確認失敗，再確認修正通過。
截至目前相關 focused suites 為 102 passed、12 subtests passed。
協定邊界回歸使用原始 HEAD 實作確認失敗（0.57 秒），修正後相關
協定、串流與延遲套件為 84 passed。

首次隔離啟動約 34 秒；Edge PCM 預熱 0.94 秒並與模型載入重疊，
本機 LLM prompt prefill 4.31 秒。預熱後 `/health` 確認 ready=true。
真實語音 8 輪初測：伺服器首音 P50 2.958 秒、P95 15.755 秒；
起點為 VAD 確認結束，另有 0.32 秒 endpoint wait，仍不含瀏覽器播放。
長回答的第一個可朗讀文字約 1.57／2.16 秒已有，首片段卻延後到
14.46／14.87 秒，與整份 LLM 完成接近。此對照暴露上述口語頻道
邊界等待，後續以同問題集重測。
資料：[voice-soak-8.json](voice-soak-8.json)。這是 8 輪診斷，不是
原 ADR 要求的 50 輪 rollout gate；沒有插話與重連驗收。報告內 A/V
offset=0 代表缺少配對，不能採其 av_offset=true 作為同步通過證據。

修正後 8 輪：[voice-soak-channel-fix-8.json](voice-soak-channel-fix-8.json)。
伺服器首音 P50 2.890 秒、P95 3.348 秒；首片段 P95 從 14.726 秒
降至 1.844 秒。第一個長回答首音從 15.570 秒降至 2.852 秒。
問題集、模型與設定相同，但模型生成文字未鎖定；樣本少，不能宣稱
正式 P95 SLO 已達標。這些值仍從 VAD 確認結束起算，另有 0.32 秒
endpoint wait，尚缺瀏覽器／喇叭播放時間。

剩餘成本可見於分段量測：ASR P50 0.403 秒；形成首片段 P50 1.774 秒；
首片段至 PCM 可用 P50 0.693 秒；首片段至 WebRTC commit P50 0.752 秒。
重疊區間不能再相加，分項分位數也不是同一輪的關鍵路徑。
TTS PCM 至 commit 的長等待已消除，下一步主要是首句生成與 TTS
網路／合成延遲；2 秒目標需要再評估首句策略、較快的模型或 TTS。
本次保留目前模型及聲音，未默認降低品質。

兩次隔離服務與其自建 llama-server 均已關閉；原服務及全域設定未修改。
程式修正需在下次啟動載入。獨立音訊仍須明確啟用隔離設定，不會
因重啟原服務自動啟用；完整數字人 A/V rollout gate 仍未通過。

完整驗證：

- `uv run python scripts/check-integration.py`：通過，含品牌及授權契約。
- `uv run pytest`：471 passed、4 skipped、1 failed，40.77 秒。
- `npm test`：84 passed。
- `npm run build`：通過。
- `git diff --check`：通過。

唯一 pytest 失敗仍是既有原尺寸背景合成效能門檻
`test_chroma_composite_fits_the_render_frame_budget_on_a_portrait_avatar`，
要求 1080×1920 合成中位數 <30ms。本次沒有改動既有
`src/scene/service.py` 的使用者變更，也未放寬門檻。
詳細檢查紀錄在本目錄 `pytest.log`、`integration.log`、
`web-test.log`、`web-build.log`，皆不納入 Git。
