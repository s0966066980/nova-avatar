<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# Matcha 聲線模型

Status: 已確認（2026-11-24），工單 01–04 已實作並通過審查修正，待 05 實機驗收

使用者想做兩件事：導入 Matcha hsiaochen-edge，並把 jetson-orin 分支的 Matcha（含訓練功能）帶進 main，要求先分析是否可行。2026-11-24 經 grilling 後定案的範圍如下；設計依據見 [ADR 0025](../../docs/adr/0025-matcha-voice-models-without-edge-distillation.md)。

## 可行性結論

**可行，但要手動移植。**

- jetson-orin 和 main 各自有兩百多個對方沒有的 commit。Matcha 的 commit `7e5ce60` 同時刪掉了 main 仍在用的 BreezyVoice 和 Edge worker 程式碼，所以不能 cherry-pick。
- 可以幾乎原樣帶過來的：`src/tts/engines/matcha.py`、`src/tts/pcm_emitter.py`（只依賴 `src.tts.base.State`）、相關測試。`src/tts/base.py` 和 `reply_streaming/channel.py` 在兩個分支間完全相同，介面相容。
- 要改寫的接線：`TTSConfig`、`overrides.py`、TTS factory 和引擎註冊、`voice_library.TTS_ENGINES`、數位人設定檔驗證、runtime settings、設定介面、locales。
- 依賴方面，只需要新增 `sherpa-onnx`（CPU）。`onnxruntime` 和 `opencc` main 已經有了。
- **最大的限制在授權，不在技術**（見下方「使用限制」）。

## 評比結果（2026-11-23，`tmp/tts-bakeoff/bakeoff.json`）

| 引擎 | 暖機首音 P50／P95 | 中文 CER | 英文 WER | 500 句有問題比例 |
|---|---|---|---|---|
| BreezyVoice | 2.48／2.94 s | 5.1% | 3.6% | 0.4% |
| Fun-CosyVoice3 | 1.77／1.89 s | 4.4% | 0.4% | 0.8% |
| Matcha base（jetson 詞典） | 0.054／0.071 s | 9.3% | 96% | 19.4% |
| Matcha hsiaochen-edge | 0.050／0.067 s | 13.2% | 5.6% | 0% |

Matcha 是在 CPU、4 條執行緒、**沒有載入 MuseTalk** 的情況下量的。當時透過一個 shim 呼叫 jetson-orin 的引擎，那個 shim 的原始碼沒有留下來。

## 已定案的決定

1. Matcha 是**可選引擎**，出廠預設仍是 Edge TTS。
2. 僅限非商用。
3. 分兩個階段：第一階段做推理引擎加 hsiaochen-edge，驗收通過後，第二階段才做訓練工作台。
4. 只移植 Matcha 相關功能；jetson-orin 的其他差異（商用就緒、systemd、:8010 單一來源等）不在範圍內。
5. 術語：**聲線模型**（見 `CONTEXT.md`）。
6. 數位人設定檔把引擎選為 `matcha`，再選一個已安裝的聲線模型；**同一個聲線模型同時負責 zh-TW 和 en-US**。
7. 品質：接受 hsiaochen-edge 的 13.2% CER，不另設字錯率門檻；實測數字寫進文件和介面說明。
8. `sherpa-onnx` 放進 lock，Matcha 測試納入現版主要基準，維持 0 失敗、0 跳過；缺少套件時測試直接失敗，不得 skip。
9. 聲線模型放在 `models/tts/<id>/`，不進 git、不自動下載，換機器時手動複製；文件附檔案清單和 SHA-256。只有結構完整、而且有使用限制標示的目錄才會列出。
10. `num_threads` 是全域伺服器設定，預設 4。`length_scale` 和 `noise_scale` 固定用預設值，第一階段不開放調整。
11. 使用限制以標示為主，系統不阻擋使用（跟 Edge 和開發用參考音檔一致）。

## 使用限制

| 項目 | 標示 | 依據 |
|---|---|---|
| `zh-tw-hsiaochen-edge` | Development only | 以 Edge `zh-TW-HsiaoChenNeural` 蒸餾而成；MSA §14(s)(iv) 禁止以 AI 服務的資料訓練任何 AI，不限商用 |
| base `dengcunqin/matcha_tts_zh_en_20251010`，及所有從它微調的聲線模型 | Research / Non-commercial | ModelScope 標示 Apache-2.0，但訓練資料沒有說明，可能含限非商用的 Baker 資料集 |
| `vocos-16khz-univ.onnx` | 依 THIRD_PARTY_NOTICES 記錄 | 標示 Apache-2.0，上游 Vocos 程式碼是 MIT，權重的訓練資料不明 |
| sherpa-onnx | Apache-2.0 | k2-fsa/sherpa-onnx LICENSE |
| Matcha-TTS 架構（第二階段才用到） | MIT | shivammehta25/Matcha-TTS LICENSE |

base 模型的目錄沒有使用限制標示檔，所以第一階段**不會被列為可選的聲線模型**，只作為第二階段的訓練起點。

## 第一階段範圍

- Matcha 引擎、聲線模型清單、數位人設定檔的選擇與驗證、設定介面，以及 notices 和安裝文件。
- 設定檔指到的聲線模型不存在時，處理方式跟 BreezyVoice 缺少參考音檔時一致：要明確提示，不能默默改用其他聲音。
- 新增或調整的路由，都要依 ADR 0021 列入 `ROUTE_ACCESS`。

### 驗收（在已載入 MuseTalk 和 LLM 的實機上）

- 舞台實際對話時有聲音，嘴型同步。
- 首音 P95 ≤ 0.7 s，以應用日誌的 `first audio:` 為準。
- 連續 50 輪對話沒有失敗。
- `.github/workflows/ci.yml` 的每個步驟，以及現版主要基準，全部通過。

## 第二階段（訓練工作台）

第二階段的範圍目前只確定兩件事：

- **不移植** Edge 老師（`distill_edge_teacher.py`），也不移植 Edge 試聽預覽。
- 老師只能用 CosyVoice3 搭配已授權的參考音檔，或者用真人錄音。產出的聲線模型標示為 Research / Non-commercial。

第一階段驗收後，再另開一輪 grilling 處理以下待決事項：

- 這台機器沒有 `.local/cosyvoice3`，也沒有 Matcha 上游程式碼：訓練環境要怎麼建立，跟 CUDA-only 的基準有什麼關係。
- 訓練會跟正在運作的數位人搶 GPU：要用什麼排程、怎麼阻擋。
- 訓練路由要歸入 ADMIN，並處理長時間背景工作的取消、恢復和日誌。
- 老師用的參考音檔怎麼驗證授權，以及訓練語料的保存和清理。
- 訓練產出的聲線模型怎麼寫入使用限制標示、怎麼驗收。

## 工單

- [01 依賴與聲線模型清單](issues/01-dependency-and-voice-model-catalog.md)
- [02 Matcha 引擎與設定檔整合](issues/02-matcha-engine.md)
- [03 設定介面](issues/03-settings-ui.md)
- [04 notices 與安裝文件](issues/04-notices-and-docs.md)
- [05 實機驗收](issues/05-live-acceptance.md)

## Follow-ups

程式碼審查（2026-11-24）後記錄、不在本輪處理：

- Edge TTS 改用 `src/tts/pcm_emitter.py` 輸出 PCM，與 Matcha 共用同一套切幀。
- `tts.ref_file` 改名：它在各引擎代表「用哪個聲音」（Edge 聲線名稱、BreezyVoice 音訊庫 ID、Matcha 聲線模型 ID），名稱已不貼切；改名需要設定檔與覆寫檔遷移。
- 現版基準 `tests/current-version-baseline.json`（尚在 main 工作目錄、未提交）的 `supported_options.tts` 需加入 `matcha`。
