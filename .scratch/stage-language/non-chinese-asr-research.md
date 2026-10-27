<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 非中國大陸來源 ASR 選型研究

查核基準日：**2026-10-27**。狀態：官方文件篩選完成；使用者接受後已本機比較 Whisper small／turbo，現用 small。

## 實作後補記

以下候選表保存訪談階段的文件查核結果。後續已直接下載官方 OpenAI 的 small／turbo 固定 revision，在本機轉換為 CTranslate2，完成 CUDA FP16 執行與中英合成語音比較。現用 small，turbo 可於控制台語音設定選擇。完整來源、授權 metadata 差異與雜湊見[模型 manifest](asr-benchmark/model-manifest.json)，品質、延遲與資源取捨見[後續報告](asr-benchmark/product-corpus-report.md)。另已完成預錄數位人模式的雙 WebRTC 舞台活動語音驗收；真人口音、噪音及即時嘴型共同負載仍未驗證。[驗收證據](verification/browser-results.json)

## 條件與建議

- 範圍是本機語音辨識（ASR／STT），須支援華語及英文、權重允許商用，且**正式選定模型的主要開發者與原始權重基座均須非中國大陸來源**（Q17 硬性要求）。不要求訓練資料完全沒有中國來源；未公開的教師與資料鏈須保留未知。
- Jetson Orin 須與 Nova Avatar 共用資源。既有程式已提供本機 faster-whisper，但當時儲存的有效 STT 設定是 FunASR，不能把架構決策當成現行設定。部署方向見 [ADR0005](../../docs/adr/0005-use-faster-whisper-for-stt.md)，免外部憑證約束見 [ADR0006](../../docs/adr/0006-support-only-keyless-speech-engines.md)。[既有來源條件](../non-mainland-llm/spec.md)僅借用來源定義，不套用其中 LLM 下載授權或測試結果。
- **優先評估 Whisper small；Voxtral Realtime 作另一家族候選。** 下表是文件條件篩選，沒有任何 Jetson 效能勝出結論；FunASR／SenseVoice 僅能作比較基線，不能正式選用。

## 候選表

| 模型（精確 ID） | 作者／地區與基座 | 參數 | 語言 | 權重授權／商用 | 本機執行與 Jetson 限制 |
| --- | --- | --- | --- | --- | --- |
| Whisper small：`openai/whisper-small` | OpenAI／美國；OpenAI Whisper 基座（主研究查核）。[官方專案](https://github.com/openai/whisper) | 244M。[官方型號表](https://github.com/openai/whisper#available-models-and-languages) | 多語版本，含中文、英文；勿選 `.en` 版本。[官方語言與型號](https://github.com/openai/whisper#available-models-and-languages) | **MIT，明確涵蓋程式與權重**；可商用、修改、再散布／銷售，須保留著作權與授權聲明。[權重聲明](https://github.com/openai/whisper#license)、[MIT 原文](https://github.com/openai/whisper/blob/main/LICENSE) | 最容易沿用現有 faster-whisper／CTranslate2；`Systran/faster-whisper-small` 明示由 OpenAI small 轉換。[官方轉換模型卡](https://huggingface.co/Systran/faster-whisper-small) 現有整合 GPU FP16／CPU INT8（主研究提供）；本次未測 Orin 延遲、記憶體或共同負載。 |
| Whisper turbo：`openai/whisper-large-v3-turbo` | OpenAI／美國；由 OpenAI large-v3 裁減解碼器 32→4 層。[官方模型卡](https://huggingface.co/openai/whisper-large-v3-turbo) | 809M。[官方型號表](https://github.com/openai/whisper#available-models-and-languages) | 99 語，含中文、英文。[官方模型卡](https://huggingface.co/openai/whisper-large-v3-turbo) | 權重 **MIT**，可商用；保留著作權及授權聲明。[官方模型卡](https://huggingface.co/openai/whisper-large-v3-turbo)、[授權原文](https://github.com/openai/whisper/blob/main/LICENSE) | 官方有本機 Transformers CUDA／CPU 範例。[官方模型卡](https://huggingface.co/openai/whisper-large-v3-turbo) 現有設定白名單不含 turbo；須另開放選項並確認 adapter／CTranslate2 支援，這些均未驗證（主研究提供）。 |
| Voxtral Realtime：`mistralai/Voxtral-Mini-4B-Realtime-2602` | Mistral AI／[法國](https://mistral.ai/fr/legal/)；語言基座 `mistralai/Ministral-3-3B-Base-2512`。[官方模型卡](https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602) | 品牌 4B；論文總計約 **4.4B**：970M 音訊編碼器＋25M adapter＋3.4B decoder。[作者論文表 1](https://arxiv.org/html/2602.11298v1#S2) | 13 語，明列中文、英文；臺灣口音、繁中輸出及中英混說品質未測。[官方發布](https://mistral.ai/news/voxtral-transcribe-2/) | **Apache-2.0**，官方明確指模型／BF16 權重且允許商用；再散布須附授權、保留適用聲明／NOTICE、註明修改；模型卡另要求不侵害第三方權利。[模型授權段](https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602#license)、[授權原文 §§2–4、6](https://www.apache.org/licenses/LICENSE-2.0.txt) | 原生串流 ASR；官方推薦 vLLM，也列 Transformers ≥5.2.0；ExecuTorch 明示未充分測試。[模型使用說明](https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602#usage) vLLM 有 ARM64 建置說明，但不能據此證明 JetPack／Orin 可用；安裝相依、精度路徑、峰值 RAM 及共同負載均未知。[runtime 官方文件](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/) |

### 基座與教師的證據邊界

- **Whisper**：主研究確認開發者及權重基座為 OpenAI；多語訓練含中文。完整教師／資料來源鏈未證實。Systran small 是 CTranslate2 格式轉換，不是另一個已訓練基座。[OpenAI 官方專案](https://github.com/openai/whisper)、[轉換說明](https://huggingface.co/Systran/faster-whisper-small)
- **Voxtral**：作者論文說音訊 encoder／adapter 隨機初始化，decoder 取自 Ministral 3B；模型卡指定上述 **Base** ID。Ministral 3 論文再明示其基座由 **Mistral Small 3.1** 剪枝與 cascade distillation 而來，預訓練教師也是 Mistral Small 3.1；因此不是只憑發布帳號推定基座來源。其他未公開教師、上游完整資料鏈仍未知；不把 Instruct／Reasoning 版本的後訓練教師直接套到這個 Base。[Voxtral 訓練 §3.3](https://arxiv.org/html/2602.11298v1#S3.SS3)、[官方模型卡](https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602)、[Ministral 3 §§1、3.1、5.1](https://arxiv.org/html/2601.08584v1)

## 排除與保留事項

- **IBM Granite Speech 不推薦作本次中英 ASR**：`ibm-granite/granite-speech-5.0-2b`（約 2B，基座為 `granite-4.0-1b-base` 的中間 checkpoint）輸入語言為英／法／德／西／葡／日；「English-to-Mandarin」是翻譯輸出，不是中文語音辨識。`ibm-granite/granite-speech-5.0-470m-turboctc`（470M）在 2026-10-21 更新為七語，新增義大利語但仍無中文。兩者模型權重卡宣告 Apache-2.0，可依其條件商用，語言仍不合。[5.0 2B 官方卡](https://huggingface.co/ibm-granite/granite-speech-5.0-2b)、[5.0 TurboCTC 官方卡](https://huggingface.co/ibm-granite/granite-speech-5.0-470m-turboctc)、[授權原文](https://www.apache.org/licenses/LICENSE-2.0.txt) 較早 `ibm-granite/granite-4.0-1b-speech` 與 `ibm-granite/granite-speech-4.1-2b` 亦只列上述六種語音輸入，故不再增加候選。[4.0 卡](https://huggingface.co/ibm-granite/granite-4.0-1b-speech)、[4.1 卡](https://huggingface.co/ibm-granite/granite-speech-4.1-2b) IBM 為[美國公司](https://www.ibm.com/downloads/documents/gb-en/10a99803d92fd6d2)；本輪因語言即淘汰，未完成其完整基座教師鏈與 ARM64 驗證。
- **NVIDIA 常見多語版缺中文**：`nvidia/parakeet-tdt-0.6b-v3`（600M）與 `nvidia/canary-1b-v2`（978M、品牌 1B）官方均列 25 種歐洲語言，沒有中文；權重適用 **CC-BY-4.0**、允許商用但須署名並標示修改，仍因語言排除。[Parakeet 官方卡](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)、[Canary 官方卡](https://huggingface.co/nvidia/canary-1b-v2)、[CC 授權原文](https://creativecommons.org/licenses/by/4.0/legalcode.en)
- **不能說整個 Parakeet 家族都不支援中文**：另有 `parakeet-ctc-0.6b-zh-cn`，600M、明確支援華語＋英文及混說；`parakeet-ctc-0.6b-zh-tw`，600M、臺灣華語繁中，官方輸出段也列中英，但其英語／混說能力未在本次驗證。作者 NVIDIA 位於[美國 Santa Clara](https://nvidianews.nvidia.com/multimedia/santa-clara-headquarters)；模型卡未完整具名初始化基座與教師，該來源鏈仍未知。[zh-CN 官方卡](https://build.nvidia.com/nvidia/parakeet-ctc-0_6b-zh-cn/modelcard)、[zh-TW 官方卡](https://build.nvidia.com/nvidia/parakeet-ctc-0_6b-zh-tw/modelcard)
- **中文 Parakeet 暫不列正式推薦**：這些本機可部署模型使用 NVIDIA Community Model License，不能套用上述 CC-BY 權重條款。原文涵蓋 learnt weights；§1.2 原則上要求正式部署使用 AI Enterprise 訂閱下的 NIM，另有特定 RTX／指定模型例外，未證實適用本專案 Orin；另有限制用模型／輸出改善其他模型等條款。官方 zh-CN 部署流程要求 NGC API key，因此尚未證實可符合本專案免外部憑證條件。[zh-CN 授權聲明](https://build.nvidia.com/nvidia/parakeet-ctc-0_6b-zh-cn/modelcard)、[zh-TW 授權聲明](https://catalog.ngc.nvidia.com/orgs/nvidia/-/collections/parakeet-ctc-0.6b-zh-tw/-)、[模型授權原文 §§1.2、2](https://www.nvidia.com/content/dam/en-zz/Solutions/license-agreements/enterprise-software/NVIDIA-Models-Community-License-2025-04-15-FINAL.pdf)、[官方部署流程](https://build.nvidia.com/nvidia/parakeet-ctc-0_6b-zh-cn/deploy) zh-TW 卡列 Riva ≥2.19、Jetson／Linux 4 Tegra；這是模型卡支援宣告，**不等於已確認目前 NIM 容器或本專案 Orin 組合相容**。[zh-TW 軟體整合段](https://build.nvidia.com/nvidia/parakeet-ctc-0_6b-zh-tw/modelcard)

## 來源紀錄與未測狀態

僅使用開發商官方網站、官方模型庫、作者論文及授權發布者原文。Voxtral 本輪核對的官方模型庫 revision：[`2769294da9567371363522aac9bbcfdd19447add`](https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602/blob/2769294da9567371363522aac9bbcfdd19447add/README.md)。IBM 最新兩版卡 revision：[`5.0-2b@c684620`](https://huggingface.co/ibm-granite/granite-speech-5.0-2b/blob/c684620bb54fc89d14ba27256b23bbc9e09ba764/README.md)、[`5.0-470m@1dd23f4`](https://huggingface.co/ibm-granite/granite-speech-5.0-470m-turboctc/blob/1dd23f46f6d4e6eae2531982ba2e33220086dd97/README.md)。Voxtral 庫未另附獨立 LICENSE 檔，已讀其**模型授權段直接引用的 Apache-2.0 全文**，不是僅採框架程式授權。其他 `main`／官方網頁可能更新。

**文件篩選階段未下載模型／容器、未執行基準或更改設定；後續實作與測試見本頁補記。** Voxtral、Granite 與 Parakeet 均未下載或驗證 Orin。未提供真人臺灣華語 CER／英文 WER、現場噪音或功耗排名；沒有把 A100、官方桌機數字、Whisper 原版 VRAM 估算或參數量當成 Jetson 實測。
