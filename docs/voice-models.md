<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->

# Matcha 聲線模型安裝

Matcha 是**可選**的 TTS 引擎，出廠預設仍是 Edge TTS。它用 sherpa-onnx 在 CPU
上執行 Matcha-TTS 的 ONNX 模型，不佔用 GPU。引擎的聲音單位是**聲線模型**：
一組固定一種聲音的權重，同時負責 zh-TW 和 en-US，不需要參考音檔。設計依據見
[ADR 0025](adr/0025-matcha-voice-models-without-edge-distillation.md)。

聲線模型不進 git，也不會自動下載。每台機器都要手動複製，複製後用下方的
SHA-256 核對。`sherpa-onnx` 已是主要依賴，執行 `uv sync` 就會安裝，不必另外處理。

## 使用限制

沒有任何聲線模型可以商用。系統只標示使用限制，不會阻擋使用。

| 聲線模型 | 標示 | 原因 |
| --- | --- | --- |
| `zh-tw-hsiaochen-edge` | **Development only** | 以 Microsoft Edge `zh-TW-HsiaoChenNeural` 的輸出蒸餾而成。Microsoft Services Agreement §14(s)(iv) 禁止以 AI 服務的資料訓練任何 AI，不分商用或非商用。只能在開發機上試用，不要上場域，也不要散佈。 |
| 從 base 模型 `dengcunqin/matcha_tts_zh_en_20251010` 微調的聲線模型 | **Research / Non-commercial** | ModelScope 標示 Apache-2.0，但沒有說明訓練資料，可能含限非商用的 Baker 資料集。 |

base 模型本身沒有使用限制標示檔，因此**不會**出現在聲線模型清單中，只作為第二階段
的訓練起點。各元件的授權見 [第三方聲明](../THIRD_PARTY_NOTICES.md#matcha-voice-models)。

## 目錄結構

每個聲線模型放在 `models/tts/<id>/`，目錄名稱就是聲線模型的 ID（英數字開頭，
只含英數字、`.`、`_`、`-`，最多 80 字）。設定只記錄 ID，不記錄路徑。

```text
models/tts/zh-tw-hsiaochen-edge/
├── voice.json                 必要：使用限制標示
├── model.onnx                 必要：聲學模型
├── vocos-16khz-univ.onnx      必要：聲碼器，輸出 16 kHz
├── lexicon.txt                必要：發音詞典
├── tokens.txt                 必要
├── phone-zh.fst               選用：電話號碼正規化
├── date-zh.fst                選用：日期正規化
├── number-zh.fst              選用：數字正規化
└── NOTICE-NON-COMMERCIAL.txt  舊說明，系統不讀取
```

缺少任何必要檔案、沒有 `voice.json`，或 `voice.json` 格式不正確的目錄都不會列出，
原因會寫進日誌（`Voice model <id> not listed: …`）。隱藏目錄和放在
`models/tts/` 底下的檔案會略過。

## `voice.json` 格式

UTF-8 編碼的 JSON 物件，四個欄位都必填，而且不能是空值：

| 欄位 | 內容 |
| --- | --- |
| `name` | 介面上顯示的名稱 |
| `usage` | 使用限制，只能是 `Development only` 或 `Research / Non-commercial` |
| `languages` | 這個聲線模型會說的語言，非空的字串陣列 |
| `source` | 權重來源 |

`zh-tw-hsiaochen-edge` 的 `voice.json`：

```json
{
  "name": "曉臻（Edge 蒸餾）",
  "usage": "Development only",
  "languages": ["zh-TW", "en-US"],
  "source": "Matcha-TTS fine-tuned from dengcunqin/matcha_tts_zh_en_20251010 on audio distilled from Microsoft Edge zh-TW-HsiaoChenNeural; see NOTICE-NON-COMMERCIAL.txt"
}
```

格式由 `src/tts/voice_models.py` 驗證。目錄裡舊的 `NOTICE-NON-COMMERCIAL.txt`
寫的是 Research / Non-commercial，比實際限制寬鬆；`source` 雖然指向它，使用限制一律以
`voice.json` 的 `Development only` 為準。

## 手動複製

1. 在來源機器上確認目錄完整，並計算雜湊：

   ```bash
   cd models/tts/zh-tw-hsiaochen-edge && sha256sum -- *
   ```

2. 把整個目錄複製到新機器專案根目錄下的 `models/tts/`，例如：

   ```bash
   rsync -a models/tts/zh-tw-hsiaochen-edge/ \
     <新機器>:<專案根目錄>/models/tts/zh-tw-hsiaochen-edge/
   ```

3. 在新機器上執行 `sha256sum -- *`，逐一比對下表。任何一個不符就重新複製，不要使用。
4. 如果來源目錄沒有 `voice.json`，照上一節的內容建立（逐字相同時雜湊會與下表一致）。
5. 重新啟動後端，到數位人設定檔「聲音」把引擎選為 Matcha，再從清單選擇聲線模型。
   設定檔指到的聲線模型不存在（例如目錄被刪除或改名）時，選擇仍會保留：角色組合與設定檔編輯器顯示
   「（未安裝的聲線模型）」，儲存設定檔、套用與試聽會被拒絕並指出缺少的聲線模型 ID，對話中每個片段
   也以同樣的訊息失敗；絕不改用其他聲音。把聲線模型複製回 `models/tts/` 即可恢復，不需要重新選擇。

## `zh-tw-hsiaochen-edge` 檔案清單

2026-11-24 在開發機上計算：

| 檔案 | SHA-256 | 大小（bytes） |
| --- | --- | --- |
| `model.onnx` | `19dd78e384e27ab1f6d19528cf5a1b2db5e5b714ad85af3342b25a7eb5a6d8c9` | 75311333 |
| `vocos-16khz-univ.onnx` | `b599142a1fb8ff03de3e84ac35ff537c619e56f4267a6fe894851a42844acf9e` | 53882848 |
| `lexicon.txt` | `fbe09e2608f09cb7d0ec21a00a157c90d8a6204cc8366e064bf7b57a8a42a949` | 7357488 |
| `tokens.txt` | `77fee8e5e5dd96b3547119e6159292c648e99e065c54c97777722e3ce710b9a4` | 21146 |
| `phone-zh.fst` | `1ac2b6fa56b1442320c4de7db08353bab8963a2b57f365eebcdd3a2d3562f8d7` | 88630 |
| `date-zh.fst` | `eb8aa079ae3cb81d8f4404992f39d61a0cb990947512b5b8d1e54d1f6980e718` | 59154 |
| `number-zh.fst` | `743f402181fcfebf76cc2f0546b71fa26476e626fbe4e460fb7b4c3a7a8bd5bd` | 64482 |
| `voice.json` | `a2b88d89ce1f18870660783072a6f32ddd56c75e8670f35df11a1df95da0b538` | 277 |
| `NOTICE-NON-COMMERCIAL.txt` | `f36cb03910d1b9ca354f5d40c9ab3a19c807983bef1d7e04b7194a0f34343420` | 350 |

`vocos-16khz-univ.onnx`、`tokens.txt` 和三個 `.fst` 檔，跟 base 模型目錄裡的同名檔案
完全相同。

## 品質與效能

2026-11-23 的評比（CPU、4 條執行緒、沒有載入 MuseTalk）：`zh-tw-hsiaochen-edge`
的暖機首音 P50 0.050 s、P95 0.067 s；中文 CER 13.2%、英文 WER 5.6%；500 句中
沒有出現有問題的輸出。CER 比 BreezyVoice（5.1%）高，但已接受，不另設門檻。
CPU 執行緒數是全域伺服器設定，預設 4。
