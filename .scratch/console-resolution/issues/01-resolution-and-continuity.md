<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->

# 控制台解析度設定與影音卡頓

Status: resolved
Type: task

## 可重現的問題

使用者確認聲音斷續、畫面同時卡頓。2026-10-06 本機 Jetson 一般模式
使用 MuseTalk、TensorRT UNet、TAESD、Edge TTS，輸出上限為 1280 像素
（720×1280）。日誌首段 2.52 秒的 PCM 需要 4.528 秒提交播放。

`audio_log_gate.py` 對當日 12:42:39 的應用日誌重播，stretch ratio 為
1.797，連續性門檻失敗。此結果只針對從 media index 0 開始的首段語音；
後續驗證直接擷取瀏覽器收到的合成語音，不錄製麥克風。

以真實角色 PNG、目前選擇的背景及 aiortc H.264 編碼器量測，1280 高度
的純輸出處理中位數 58.76 ms、P95 65.94 ms，已超過 25 fps 的 40 ms
預算，尚未包括嘴型推理、貼回及瀏覽器工作。音訊隨 renderer 交付，
輸出處理慢會插入播放空隙；成功收到 RTP 並不代表原始語音連續。

## 實作

- 控制台「系統設定中心 → 數位人與畫質」新增輸出高度選單、素材比例
  換算尺寸、儲存按鈕、錯誤訊息與重新連線提示。
- `POST /api/avatar/output` 驗證整數高度，原子保存 runtime overrides。
  其他設定存檔也保留解析度。新 avatar 使用獨立配置快照，既有連線與
  錄影保留原尺寸，避免串流中途變更尺寸。
- 輸出縮圖先使用精確 2:1 的 INTER_AREA 縮小，再對較小影像作最後
  比例縮圖；保留抗鋸齒、比例及偶數輸出尺寸，不重新製作素材。
- 沒有啟用尚未通過影音同步驗收的獨立音訊實驗模式。

## 輸出處理量測

`measure_output.py` 只量測縮圖、背景合成和實際 H.264 編碼，使用
22 張真實角色影格，排除頭兩張暖機。量測不是整條 GPU 推理鏈的保證。

540 高度（304×540）優化前中位數 32.18 ms，優化後 17.07 ms、
P95 19.24 ms。1280→540 的解析度降低與縮圖優化共同提供處理餘裕。
單張真實影像相對直接 INTER_AREA 縮圖的 540 高度 PSNR 為 46.73 dB；
960 高度逐像素相同。沒有更改綠幕去溢色或嘴型演算法。

## 驗證

- focused Python：76 passed、1 skipped、10 subtests passed。
- 前端：90 tests passed；production build passed。
- 品牌、授權與 Python 整合稽核：passed。
- 全套 Python：522 passed、4 skipped、50 subtests passed、1 failed。
  失敗是原有 `test_chroma_composite_fits_the_render_frame_budget_on_a_portrait_avatar`：
  1080×1920 全尺寸背景合成中位數 35.68 ms，高於 30 ms 門檻。
  未修改該演算法、測試或門檻。

## 真實控制台與影音驗證

以 Playwright 驅動真實 Vue 控制台與現有 GPU backend，確認：

- 儲存 540 高度後重新整理，選項仍為 540。
- 連線中儲存 960，收到重新連線提示，既有影像保留 304×540。
- 中斷並重新連線後實際 video dimensions 為 540×960。
- 再儲存 540 並重新連線，實際影像為 304×540。

效能也受到背景工作的影響。背景索引最高曾使用約五個 CPU 核心；
索引執行時的測試仍可出現約 21–22 fps 與音訊補音。暫停索引的
相同 headed 朗讀對照回到約 24.2–24.4 fps，三輪音訊補音均為零。
降低解析度無法保證在其他程式高負載時仍完全流暢。

headed 回呼取樣曾有 200 ms 的間隔，但期間 presentedFrames 增加 5；
這種回呼漏取樣不能直接當成整段畫面凍結。
[requestVideoFrameCallback 規格](https://wicg.github.io/video-rvfc/)
說明回呼可能晚到或漏取樣。移除診斷工具的 canvas/GPU 畫面讀回操作，
保留影格 metadata 與實際接收的合成 PCM，再使用 headless Chromium
在暫停索引的條件下執行原本的 <=120 ms 間隔、>=23 fps、零補音及
零 freezeCount 門檻，三輪全部通過：

| 輪次 | 呈現 fps | 最大回呼間隔 | 語音有效跨度 | 補音 samples | 凍結次數 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 24.21 | 66.7 ms | 9.988 s | 0 | 0 |
| 2 | 24.42 | 66.6 ms | 9.976 s | 0 | 0 |
| 3 | 24.42 | 66.8 ms | 9.998 s | 0 | 0 |

完整資料見 [controlled-540.json](../controlled-540.json)。參考 Edge TTS
檔案長度 10.992 秒，包含前後靜音；實際收到的語音沒有超過參考長度
15% 的播放延長。所有測試只使用固定合成文字，不取得麥克風。
索引 daemon 與 worker 都由 finally 恢復，沒有永久停用背景服務。

## 使用與限制

目前一般模式已保存 540 高度。重新整理控制台後，在「系統設定中心
→ 數位人與畫質 → 數字人輸出解析度」可選擇高度；儲存後中斷再啟動
連線。540 對此直式素材是 304×540，960 是 540×960，選項不是固定
橫式 540p/960p。較高解析度增加背景合成、編碼與頻寬成本。

流暢度優先可使用 450/540；要更多畫面細節可試 960 並觀察流暢度。
播放時避免並行執行大量程式索引、模型評測或編碼工作。這次通過的
門檻限於上述單一連線、固定朗讀與受控負載；沒有宣稱高背景負載、
遠端網路、麥克風對話及長時間多輪負載也全部通過。

重測（使用現有 GPU backend）：

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  .venv/bin/python .scratch/console-resolution/measure_output.py \
  --height 540 --check
uv run --no-project --with playwright --with numpy python \
  .scratch/console-resolution/verify_console.py --playback-only --headless
```

瀏覽器重測腳本不會自行停止背景工作；需先確認後端已就緒且沒有
其他活動連線。診斷工具會保存固定合成語音與影格 metadata 供比較。
