<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# Whisper small／turbo：Jetson Orin 有限實測

日期：2026-10-27。實測時間 11:52:28–11:53:12（Asia/Taipei）。**本輪建議採 small 的既有本機資產；尚未通過自然混說或數位人完整共同負載驗收。** small 在這批素材較快且程序 RSS 較低；turbo 沒有呈現可抵銷資源增加的品質優勢。這是六段有限素材的觀察，不能推廣為兩個模型的一般排名。[原始結果](summary.json)

## 可整合的實際路徑與來源

| 型號 | 已成功載入的絕對路徑 | 官方來源與固定 revision | 實際 runtime |
| --- | --- | --- | --- |
| small | `/home/oliver/nova-avatar/models/whisper-small` | [`openai/whisper-small@973afd24965f72e36ca33b3055d56a652f456b4d`](https://huggingface.co/openai/whisper-small/tree/973afd24965f72e36ca33b3055d56a652f456b4d) | faster-whisper／CTranslate2，CUDA FP16 |
| large-v3-turbo | `/home/oliver/nova-avatar/models/whisper-large-v3-turbo` | [`openai/whisper-large-v3-turbo@41f01f3fe87f28c78e2fbf8b568835947dd65ed9`](https://huggingface.co/openai/whisper-large-v3-turbo/tree/41f01f3fe87f28c78e2fbf8b568835947dd65ed9) | faster-whisper／CTranslate2，CUDA FP16 |

直接下載 OpenAI 官方 safetensors，在本機 CPU 逐一轉為 CTranslate2 FP16；沒有使用 Systran／其他第三方微調，也沒有訓練或蒸餾。兩份 safetensors 均與固定 revision 的上游 LFS SHA-256 相符，轉換產物另記 SHA-256。原始檔保留在各目錄 `source-openai/`，可整合的 `model.bin`、`config.json`、`tokenizer.json` 位於模型目錄根層。[模型／檔案 manifest](model-manifest.json)、[準備腳本](prepare_assets.py)

OpenAI 原始專案明確將程式及模型權重採 MIT，可商用並須保留授權／著作權聲明；已將固定 commit 的原文保存於兩個模型根目錄 `LICENSE`。**官方 small Hub 卡 metadata 卻標示 Apache-2.0，turbo 標示 MIT**，此差異保留在 manifest，沒有靜默覆寫上游卡；兩種授權皆允許附條件商用。本研究的 MIT 權重依據是 OpenAI 明示涵蓋權重的原始專案，不是 CTranslate2 程式授權。[OpenAI 固定版授權範圍](https://github.com/openai/whisper/tree/86098128c0b4f24f0e2aa2994de830614b474227#license)、[MIT 原文](https://github.com/openai/whisper/blob/86098128c0b4f24f0e2aa2994de830614b474227/LICENSE)、[本機授權紀錄](license-source.json)

開發者及基座均為 OpenAI，符合 Q17 的開發者／基座來源條件；完整訓練資料與教師鏈仍未證實，不能宣稱整條供應鏈沒有中國來源。[先前來源研究](../non-chinese-asr-research.md)

## 測法與環境

- Orin ARM64，Linux `6.8.12-1021-tegra`、L4T R39.2.1，約 61 GiB RAM；原本就是 **MAXN**，前後查詢一致。驅動 595.78／CUDA driver 13.2；Python 3.11.16、faster-whisper 1.2.1、CTranslate2 4.8.2、Transformers 4.46.0。[環境前快照](environment-before.json)、[後快照](environment-after.json)
- 逐一模型、各自新 worker 程序，只有一個待測模型載入；模型載入一次、首段辨識一次、六段各暖測兩次，共 **26 次辨識**。small 先、turbo 後；沒有交錯隨機化，不是嚴格統計比較。[執行腳本](benchmark.py)、[small 記錄](results-small-cuda.json)、[turbo 記錄](results-large-v3-turbo-cuda.json)
- `language=None` 自動偵測、`task=transcribe`、`beam_size=5`、`vad_filter=False`，其餘使用已安裝 faster-whisper 預設；計時包含音檔解碼、特徵與完整 lazy segment iterator，沒有把只建立 iterator 當作完成。沒有 ASR batch、HTTP、瀏覽器、收音／輪次 VAD 或 TTS 時間。[執行腳本](benchmark.py)
- 「冷」是新模型 worker 的第一次辨識；未清 OS 檔案快取。import 與 CUDA 記憶體查詢建立 context 在載入計時之前，因此載入＋首段**不是完整產品啟動時間**。暖測每次仍有音檔處理。[執行腳本](benchmark.py)
- 全程未停背景服務；RAGFlow、Elasticsearch、MySQL、MinIO、Ollama embedding 的 PID／啟動時間前後一致。**沒有偵測到 Nova Avatar 主服務或活動嘴型渲染**，故本輪只證明背景服務共存，不能代稱數位人完整共同負載。正式設定檔雜湊與功耗查詢前後相同。[程序與雜湊核對](summary.json)

## 實際結果

| 指標 | small | large-v3-turbo |
| --- | ---: | ---: |
| 模型載入 | 0.605 秒 | 1.087 秒 |
| 首段「冷」辨識（同一中文段） | 1.362 秒 | 2.057 秒 |
| 載入＋首段辨識 | 1.967 秒 | 3.144 秒 |
| 六段暖測整體中位數 | **0.885 秒** | 1.564 秒 |
| 暖測最小–最大 | 0.629–1.595 秒 | 1.369–2.133 秒 |
| 程序載入前／後 RSS | 0.364／1.026 GiB | 0.364／2.313 GiB |
| 程序 RSS 取樣峰值（每 100ms） | **1.663 GiB** | 2.999 GiB |
| 測量期間整機最低可用 RAM | 40.566 GiB | 40.312 GiB |
| 中文近似 CER，兩段合計 | **2.22%** | 4.44% |
| 英文近似 WER，兩段合計 | 2.56% | 2.56% |
| 拼接混語近似 CER，兩段合計 | 36.55% | 65.97% |

數字由[原始結果](summary.json)彙整。Orin 是共享記憶體，`nvidia-smi` 無法提供本次每程序 GPU 記憶體；CUDA 查到的是**全裝置**已用記憶體（small 前／峰值 20.438／21.096 GiB、turbo 19.833／21.350 GiB），包含既有負載與系統配置，不能當作模型 VRAM，也不能再加到 RSS 算實體 RAM。

| 素材 | 秒數 | small 暖測中位 | turbo 暖測中位 | 品質觀察 |
| --- | ---: | ---: | ---: | --- |
| `zh_fixture_01` | 10.99 | 0.824 秒 | 1.638 秒 | small 正規化後無字元錯誤；turbo 把「整段」辨為「診斷」。 |
| `zh_fixture_02` | 22.27 | 1.501 秒 | 2.105 秒 | 兩者都出現「聞名→文明」等差異；字型變體也影響 CER。 |
| `en_openai_jfk` | 11.00 | 0.649 秒 | 1.404 秒 | 兩者英文 WER 0%。 |
| `en_hf_librispeech` | 5.86 | 0.643 秒 | 1.386 秒 | 兩者把參考 `MISTER` 寫成 `Mr.`，近似 WER 因縮寫算一個替換。 |
| `mixed_splice_zh_en` | 22.34 | 0.964 秒 | 1.532 秒 | **兩者都漏掉後面的英文段。** |
| `mixed_splice_en_zh` | 17.20 | 1.144 秒 | 1.670 秒 | small 保留兩語；turbo 漏掉前面的英文段。 |

六段的完整預期文字、原始逐字、語言偵測、每次時間與錯誤數見 [CSV](transcripts.csv) 及 [JSON](summary.json)；兩次暖測各段逐字一致。CER 將 Unicode NFKC、大小寫、OpenCC `s2t`、標點／空白正規化後做 Levenshtein；英文 WER 以單字切分，不展開 `Mr.`。保留未統一繁簡的 CER，避免掩蓋原始輸出字型。混語 CER 是字元指標，包含英文字母，**不是自然混說的合格率**。[計算實作](benchmark.py)

## 素材與阻礙

先尋找既有音訊，找到兩份有確切合成文字的中文 Edge 播放來源，不使用麥克風收音。原計畫另產六題獨立中／英／混語問題；已安裝 Edge TTS 7.2.8 回傳 websocket HTTP 403，一次程序內依官方上游改用協定版本 `2` 仍失敗，因此停止擴查。沒有改正式 Edge 套件、聲音或 API 設定。403 的服務端根因未解，不宣稱已修好。[失敗記錄](prepare-audio.log)、[單次探測](prepare-audio-protocol2.log)、[官方當時程式](https://github.com/rany2/edge-tts/blob/bd44c1d1aaebdc1db7f47456ee12431b42ec7cac/src/edge_tts/constants.py)

改採 **兩段既有中文合成音訊＋OpenAI 官方 JFK 測試音訊＋Hugging Face 官方 LibriSpeech 測試切片**，再拼出兩段跨語言探測，合計六段但僅四份獨立底層錄音，總長 89.66 秒。英文 LibriSpeech 來源是 CC-BY-4.0 語料；其作者及來源已記錄，沒有把音訊重新宣告為專案 Apache-2.0。[音訊 manifest](audio-manifest.json)、[OpenAI 固定測試音訊](https://github.com/openai/whisper/blob/86098128c0b4f24f0e2aa2994de830614b474227/tests/jfk.flac)、[HF 固定資料版](https://huggingface.co/datasets/hf-internal-testing/librispeech_asr_dummy/tree/5be91486e11a2d616f4ec5db8d3fd248585ac07a)、[LibriSpeech 原始來源／授權](https://www.openslr.org/12/)

這些是乾淨合成音、公開朗讀／演說與拼接壓力探測，**不是臺灣真人口音、麥克風雜訊、自然句內中英混說或真實問句驗證**。常見公開範例也可能與模型訓練重疊。不能以六段粗略錯誤率決定一般品質勝負。

轉換另遇 `WhisperForConditionalGeneration.__init__() got an unexpected keyword argument 'dtype'`：CT2 4.8.2 的 converter 傳新參數名稱，已安裝 Transformers 4.46 需 `torch_dtype`；只在研究 converter subclass 轉接該名稱，沒有改模型權重語義或安裝依賴。[轉換腳本](prepare_assets.py)、[最初錯誤](prepare-assets.log)、[成功轉換記錄](convert-assets.log)

兩個實際推論均成功使用 CUDA FP16，所以未啟動條件式 CPU INT8 重試。另查本機 CT2 CPU supported types 只列 `float32`，不能因產品 adapter 寫了 `int8` 就宣稱 CPU INT8 已驗證。獨立 PyTorch 探測曾警告其 wheel 未涵蓋 Orin SM87；本輪證實的是 CTranslate2 路徑，不是 PyTorch 嘴型 GPU 路徑。[環境與實測](environment-before.json)、[small runtime](results-small-cuda.json)、[turbo runtime](results-large-v3-turbo-cuda.json)

## 重跑與交付邊界

已有資產與素材時，從 repository 根目錄執行（會再次執行模型推論，保持逐一載入）：

```bash
PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 .venv/bin/python .scratch/stage-language/asr-benchmark/benchmark.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python .scratch/stage-language/asr-benchmark/summarize.py
```

只寫入本研究目錄與兩個新模型目錄；未改產品原始碼／正式設定，未重啟服務、變更 `nvpmodel`、下載 Voxtral 或啟動額外模型。研究 worker 已退出。後續產品實作可採上述 small 路徑，但自然混說保真度、臺灣真人音訊及數位人共同負載仍須另行驗收；本輪漏掉的英語片段是需要保留的失敗案例。

## 後續補記：產品 adapter 與新問題組

本報告前述 403 是直接呼叫 Edge 舊 host 的歷史觀察，當時繞過產品 `_edge_communicate` 的 endpoint 遷移，**不代表產品 Edge TTS 無法工作**。後續已由實際產品 helper 成功合成八題中／英／句內混語問題，兩模型重新配對測量；新素材沒有整段英文遺失，但仍有核心詞失真，且 turbo 在 `book` 一題比 small 保留更完整。新的服務常駐負載與舊輪不同；詳細逐字、時間、發音查核與負載限制以[產品語料補測報告](product-corpus-report.md)及[配對原始結果](product-corpus-stable-summary.json)為準。原始 fallback 結果與失敗記錄保留，不以新結果覆寫。
