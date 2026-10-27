<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 產品 Edge adapter 新問題組：品質與漏段補測

2026-10-27。**八題新素材沒有重現整個英文段消失；但 small 在兩題混語有核心詞失真，turbo 在其中一題保留較好，另一題兩者均未保真。** 不能由此宣告自然混說或臺灣真人口音驗收通過。[配對結果與完整逐字](product-corpus-stable-summary.json)

## 修正先前 403 的適用範圍

先前確實觀測到直接 `edge_tts.Communicate` 連舊 host 回傳 403；那次繞過產品的 `_edge_communicate`。產品 helper 會呼叫 `configure_edge_endpoint` 遷移到 `api.msedgeservices.com`，因此**不能把先前直接呼叫失敗解讀為產品 Edge TTS 故障**。本輪透過實際 `_edge_communicate(text, voice).save(...)` 八題全數成功，沒有修改產品、套件、正式設定或 endpoint 設定檔。[產品 helper](../../../src/tts/engines/edge.py)、[連線實作](../../../src/tts/edge_connection.py)、[本輪生成腳本](product_adapter_corpus.py)、[生成記錄](product-adapter-corpus.log)。原始失敗觀察與 fallback／multilingual 追測原檔全部保留。主研究另有[產品與連線池成功證據](../edge-diagnosis/product-results.json)。

## 素材與發音查核邊界

獨立撰寫 **2 題華語、2 題英文、4 題句內混語**，每題都是一次 TTS 合成，沒有拼接。中文用 `zh-TW-HsiaoChenNeural`，英文用 `en-US-JennyNeural`，混語用實際成功產音的 `en-US-EmmaMultilingualNeural`。八段共 31.39 秒；文字、voice、WAV／MP3 SHA-256、adapter 原始檔 SHA-256 均留存。[素材 manifest](product-audio-manifest.json)

Microsoft 官方列 EmmaMultilingual 支援英文、華語及臺灣中文，與本輪成功的 Edge 同名 voice 合成相符。[Microsoft 多語聲音表](https://learn.microsoft.com/en-us/azure/cognitive-services/speech-service/speech-synthesis-markup-voice) 三題混語的兩模型輸出都同時出現中文與英文詞串，可作實際雙語內容的交叉佐證；剩下英語句內「退貨流程」一題，兩者都輸出近音英文字串。**未做人耳／獨立音標聽辨；多語能力文件、合成輸入與兩 ASR 的核對不是獨立發音 ground truth**，不能單憑那題的共同失真把全部責任歸到 ASR。這仍是乾淨合成語音，不是真人收音、口音或噪音測試。

## 逐題觀察

以下依預期意思及關鍵詞檢視，不將數字正規化、`No.`／`number` 或繁簡差異當成語意漏段。這是非盲測的小組人工語意複核，不提供一般 WER 排名。[完整預期與原始逐字](product-corpus-transcripts.csv)

| 題目／核心內容 | small | turbo |
| --- | --- | --- |
| 請問訂單編號一二三的進度？ | 保留訂單、123、進度。 | 同樣保留。 |
| 博物館明天幾點開門，星期六需要預約嗎？ | 保留完整問題。 | 同樣保留。 |
| What time does the museum open tomorrow? | 保留完整問題。 | 同樣保留。 |
| Could you check the status of my order and explain the return policy? | 保留完整問題。 | 同樣保留。 |
| 請幫我查一下 **order number A B C one two three** 的進度。 | `Order No. ABC 123`，訂單號與中文問題保留。 | `Order Number ABC123`，同樣保留。 |
| 這個 **product** 有沒有 **warranty** 和 **return policy**？ | 中文問句及三組英文關鍵詞都保留。 | 同樣保留。 |
| Can you explain **退貨流程** and tell me how many days it takes? | 關鍵中文成為 `to a Hualou chung`，未保留「退貨流程」詞形；英文其餘問題保留。 | 關鍵中文成為 `to a huo leocheng`，同樣未保真。 |
| 我想 **book a meeting room**，明天 **morning** 還有空位嗎？ | `我想播给meeting room`；`book` 動作失真，其他中英詞串保留。 | 保留 `book a meeting room`、`morning` 及中文問題。 |

因此不能再把舊拼接素材的「英文整段遺失」直接套到本輪句內混語；本輪也不能說 turbo 完全沒有品質優勢，因為 `book` 題確有改善。沿用 small 是低延遲的取捨，需明確保留上述混語失敗案例，而非宣稱所有混語已合格。

## 同一新語料、相近背景下的時間

使用原先固定來源的兩個本機 CTranslate2 模型，CUDA FP16；`language=None`、`beam_size=5`、`vad_filter=False`，維持基準預設 `multilingual=False`，沒有再做旗標變體。各新 worker 一次不計分暖機，每題各暖測一次，候選依序載入。先跑的一輪遇到後端 RSS 在 turbo 期間增加約 0.38 GiB，故保留[初輪](product-corpus-summary.json)，另以同一素材做一次短配對重測；兩輪每題逐字均相同。[腳本](product_corpus_benchmark.py)、[配對原始 small](product-corpus-stable-small.json)、[turbo](product-corpus-stable-large-v3-turbo.json)

| 配對重測指標 | small | turbo |
| --- | ---: | ---: |
| 八題暖測中位 | **0.575 秒** | 1.327 秒 |
| benchmark 程序 RSS 取樣峰值 | 1.591 GiB | 2.984 GiB |

配對時間為 12:10:30–12:11:04（Asia/Taipei）。後端 PID `2378314` 與 Gemma LLM PID `2378506` 等常駐程序在兩候選前後一致；後端 RSS 約 2.226 GiB，LLM 約 4.307 GiB，CPU 累積時間變化很小，觀測到的正式設定雜湊及 MAXN 功耗模式一致。**與舊測不同，現在已有產品後端與 LLM 常駐**；不能把本表與先前較長的 fallback 語料耗時直接比較。主研究說明本輪部署採預錄數位人；本測只核對常駐程序，沒有主動施加播放、TTS、LLM 生成或嘴型壓力，不能稱為完整活動數位人驗收。[負載快照與核對](product-corpus-stable-summary.json)

診斷腳本對後端使用 plain HTTP `/health` 時被斷線，LLM `/health` 回 200；這不是後端健康驗收，不能據此將斷線解讀為產品故障。未變更協定／服務來配合探測。配對重測與初輪各 16 次計分辨識、另各 2 次暖機，合計 36 次；所有研究 worker 已退出，產品服務保留。

重跑新素材配對（不下載模型，不改設定）：

```bash
PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 .venv/bin/python .scratch/stage-language/asr-benchmark/product_corpus_benchmark.py --run-id product-corpus-rerun
```
