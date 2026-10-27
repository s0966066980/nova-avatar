<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# small 的 multilingual=True 單次追測

2026-10-27。**本批六段逐字與基準完全相同，沒有改善混語漏段，因此本次沒有支持為改善保真度而切換產品設定的證據。** 不宣稱自然中英混說已驗證。[追測原始 JSON](variant-small-multilingual-true.json)、[基準結果](results-small-cuda.json)

只使用 `/home/oliver/nova-avatar/models/whisper-small`，CUDA FP16、faster-whisper 1.2.1；確認本機 `WhisperModel.transcribe` 接受 `multilingual=True`，其 docstring 為每 segment 偵測語言。其餘 kwargs 與基準相同：`language=None`、`task=transcribe`、`beam_size=5`、`vad_filter=False`，其餘沿用原預設。新 worker 先做一次不計分暖機，再對六份原素材各暖測一次。[可重跑腳本](probe_multilingual.py)

| 素材 | 基準暖測中位（兩次） | multilingual=True（一次） | 逐字／漏段差異 |
| --- | ---: | ---: | --- |
| `zh_fixture_01` | 0.824 秒 | 0.852 秒 | 完全相同。 |
| `zh_fixture_02` | 1.501 秒 | 1.422 秒 | 完全相同。 |
| `en_openai_jfk` | 0.649 秒 | 0.658 秒 | 完全相同。 |
| `en_hf_librispeech` | 0.643 秒 | 0.624 秒 | 完全相同。 |
| `mixed_splice_zh_en` | 0.964 秒 | 0.838 秒 | 仍漏掉後面的英文段。 |
| `mixed_splice_en_zh` | 1.144 秒 | 1.384 秒 | 同樣保留兩語。 |

暖測整體中位由基準 0.885 秒變為本次 0.845 秒；分開執行且僅一次暖測，不能據此主張穩定加速。兩段拼接混語加權近似 CER 仍為 **36.55%**。完整預期文字、兩版逐字、segment、語言偵測及每段時間均保留在[追測 JSON](variant-small-multilingual-true.json)。拼接錄音不是自然句內混說，資料限制見[原報告](report.md)。

追測程序已正常退出；沒有改產品原始碼、套件、正式設定、功耗或重啟服務。追測期間正式設定雜湊與功耗查詢前後一致。[前後快照及核對欄位](variant-small-multilingual-true.json)
