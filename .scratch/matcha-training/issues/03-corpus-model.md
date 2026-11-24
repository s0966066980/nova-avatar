<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 訓練語料資料模型
Status: ready-for-agent

依[規格](../spec.md)第 2、3、5、6、7 點與 `CONTEXT.md`「訓練語料」「使用限制標示」。

- 語料資料夾 `data/tts/training/<slug>/`：音檔、逐字稿、每句的校對狀態（待確認／已確認／已排除）、來源宣告（測試用老師、自己錄的、有書面授權、開發用）。
- 使用限制標示的計算：取底模與語料來源中最嚴格者，Edge 或開發用 → Development only，其餘 → Research / Non-commercial；可單獨測試。
- 數字與日期展開成中文字的標準化器，展開不了的回報為待處理。
- 所有路徑由伺服器產生，slug 與檔名都要檢查。
- 只做資料層與純函式，不新增路由；測試使用自足的 fixture，0 失敗、0 跳過。

## Comments

### 2026-11-24 實作摘要（分支 `mv2/03-corpus-model`）

純資料層，沒有路由、GPU、網路或模型載入。位置放在 `src/tts/training/`：與 `src/tts/voice_models.py` 同屬 TTS 領域，訓練產出的聲線模型 slug 就是 `models/tts/<slug>/` 的 ID，所以直接重用 `VOICE_MODEL_ID`。新測試 174 個（`tests/test_training_{numerals,usage,corpus}.py`），無跳過，已登記在 `tests/conftest.py` 的 `speech` 區。

**公開介面（給 04、05、06）**

- `src.tts.training.corpus.CorpusStore(root=None)`，預設根目錄 `data/tts/training/`：`create(slug, source=None)`、`get`、`list`、`declare_source`、`add_line(slug, audio_bytes, extension, text="", original_name="")`、`set_text`、`set_review`、`audio_path(slug, line_id)`。回傳不可變的 `Corpus`、`Line`。
- `Corpus`：`counts`、`review_table()`（每句附 `NormalizedText`）、`trainability()`（`trainable` 加原因碼 `source_missing`、`pending_lines`、`no_confirmed_lines`、`unresolved_digits`）、`training_lines()`（僅可訓練時回傳已確認句子與展開後文字，否則 `CorpusError` 409）、`usage_label(base_usage=None)`。
- `CorpusError(message, status)`，訊息為繁體中文，路由可直接轉成回應。
- `src.tts.training.usage`：`SOURCE_KINDS`、`corpus_usage_label(source, base_usage=BASE_MODEL_USAGE)`、`strictest_label`，標示字串取自 `voice_models.USAGE_LABELS`。
- `src.tts.training.numerals.normalize_digits(text)` 回傳 `NormalizedText(text, unresolved)`；`Unresolved(text, start, end, reason)` 的位置指向原文。

**設計選擇**

- 磁碟：`corpus.json`（UTF-8，原子寫入）加 `audio/<六位數 ID><副檔名>`。ID 由伺服器產生，副檔名限 wav、mp3、flac、ogg、m4a、webm；上傳檔名只存成顯示文字，不參與路徑。slug 與 ID 以 `fullmatch` 檢查，符號連結的語料資料夾與音檔一律拒絕，從磁碟讀回的清單也重新驗證。一把模組層級的鎖保護讀改寫（Edge 合成執行緒與校對可能同時進行）。
- 來源宣告只能設定一次，之後不可更改（同值重複宣告無效果）：標示由它決定，「處理不降級」因此由資料模型保證；要換來源就建立新語料。未宣告時標示取最嚴格的 Development only，且不可訓練。
- 編輯已確認句子的文字會退回待確認；待確認、已排除不變。沒有逐字稿的句子不能確認。
- `unresolved_digits` 只計已確認的句子（規格原文）；校對表可先確認再被擋，管理者改文字即可解除。
- 不提供刪除語料：刪除要先查訓練工作是否使用中並移入 `.deleted`（CODING_STANDARDS 4），留給 06 一併處理。
- 音檔只檢查大小（32 MB）與副檔名，沒有解碼或內容嗅探；格式轉換、16 kHz 與長度品質檢查屬 05 與 06。

**標準化慣例**（完整清單在 `numerals.py` 模組文件）

- 展開：整數讀為數量（15 → 十五、101 → 一百零一）；2 一律「二」，不用「兩」，錄音念「兩個」須手改文字；千分位逗號（1,234）；剛好四位數加「年」逐位讀（2026年 → 二零二六年），一至三位加「年」讀數量；一至二位加「月、日、號」讀數量並去前導零；小數（3.5 → 三點五）；百分比（50% → 百分之五十）；電話與長數字逐位讀、1 讀「一」、連字號省略（含前導零、八位以上、台灣區碼格式）；全形數字視同半形。
- 不猜、回報待處理（原文保留）：`currency`、`time_or_ratio`、`numeric_date`、`slash`、`range`、`mixed_unit`（5kg、GPT4、COVID-19、3x4）、`dotted`、`signed`、`degree`、`permille`、`ambiguous_year`（無「年」的 1900 至 2099 四位數）、`ambiguous_long_number`（五至七位無逗號）、`ambiguous_decimal`。
- 不變條件：任何 ASCII 數字要不是被展開，就是在待處理清單裡，不會被丟掉。

**驗證**：基準（`matcha-training` tip）2 failed、1564 passed、3 skipped；本分支 2 failed（同兩項，PDF OCR 與 role coordinator）、1738 passed、3 skipped。lock check、ruff、pyright（CI 設定 0 錯誤，另對 `src/tts/training` 單獨執行也是 0）、`check-integration.py` 通過；未動 `web/`，略過網頁步驟。
