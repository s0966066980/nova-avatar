<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# Matcha 訓練工作台

Status: 已確認（2026-11-24），疊音／跳音診斷已完成，待介面原型

這是 [Matcha 聲線模型](../matcha-voice/spec.md)的第二階段。管理者在控制台用 Edge 朗讀聲音（測試用）或自己上傳的錄音訓練聲線模型，逐字稿可上傳或自動產生並校對，訓練完成後成為可選的聲線模型。設計依據見 [ADR 0026](../../docs/adr/0026-edge-as-test-only-matcha-teacher.md)，術語見 `CONTEXT.md`（使用限制標示、訓練語料、測試用老師、訓練工作）。

## 已取消

聲線變造與聲線轉換（音高、共振峰、語速、EQ 步驟鏈，以及 kNN-VC 等轉換工具）已由管理者在 2026-11-24 取消開發，相關的開源工具調查也已停止。這條線若日後重啟，仍須遵守「語料經過任何處理，來源不變」的標示規則。

## 已定案的決定

1. 先修第一階段的疊音與跳音，再做訓練工作台。
2. Edge 當測試用老師：只在控制台管理者登入後可用，介面顯示 MSA §14(s)(iv) 條文，勾選確認才能開始；產出一律標示 Development only，不提供匯出。
3. 使用限制標示取底模與語料來源中最嚴格者：Edge 語料 → Development only；自錄或有書面授權的語料加 base 底模 → Research / Non-commercial。
4. Edge 老師的聲音：下拉選單列出 Edge 的 zh-TW 聲音，預設 HsiaoChen；英文句由同一個聲音念。文字來自內建句庫（約 900 句，相當 1 小時）或管理者上傳的文字檔，不用 LLM 產生。份量有「快速測試」（約 15 分鐘）與「標準」（約 1 小時）兩個預設。沿用逐句送出、失敗重試與間隔等待，避免被限流。
5. 上傳自己的錄音時必須宣告來源：自己錄的、有書面授權、開發用（未取得授權）。前兩者勾選聲明；開發用只能產出 Development only。
6. 逐字稿可上傳同檔名的 `.txt` 或 `metadata.csv`（`檔名|文字`），也可用 faster-whisper 自動產生並轉成繁體中文。自動產生的進入校對表，可逐句修改、試聽、排除，全部確認後才能訓練。
7. 訓練前把阿拉伯數字和日期展開成中文字，顯示在校對表讓管理者確認；無法處理的標出來，不進訓練。
8. 訓練環境是獨立的 venv（`.local/matcha-train/`），不裝進主程式 `.venv`；先做實驗確認上游 `matcha-tts` 能嚴格載入底模權重。
9. 訓練以獨立子程序執行。有舞台連線，或剩餘顯存低於門檻（初始 8 GB）時拒絕開始，介面顯示原因並停用按鈕。
10. 先用 ui-ux-pro-max 做可點擊的 HTML 原型與設計說明，管理者確認後才實作介面。jetson 的 `TtsTrainingPanel.vue` 只當參考。
11. 第一版不含 CosyVoice3 老師、聲線變造與轉換、多說話者。

## 技術事實（2026-11-24 調查）

- 微調需要 PyTorch 權重。ModelScope `dengcunqin/matcha_tts_zh_en_20251010` 有 `pytorch_model_sherpa.bin`（約 75 MB，授權欄標 Apache-2.0，訓練資料未說明）。本機沒有任何 Matcha 權重或上游程式碼。
- PyPI `matcha-tts` 0.0.7.2 只有 cp310 wheel，依賴很重（`gradio==3.43.2`、`hydra-optuna-sweeper`、`conformer`、`diffusers`、`lightning` 等）。jetson 分支用的是 CosyVoice 內附的 `third_party/Matcha-TTS`。上游版能否嚴格載入該權重尚未驗證。
- 訓練端的文字轉 token（`lexicon_utils.text_to_phoneme_ids`）沒有推理時的規則轉換（`number-zh.fst` 等），阿拉伯數字和日期會被直接丟掉；推理端則有。數字必須先展開，否則音檔與文字對不上。
- 取樣率固定 16 kHz。品質檢查（`audio_qc.py`）：頭尾靜音修剪、長度 0.5–15 秒、RMS 與峰值正規化、用 faster-whisper 比對與文字的相似度（門檻 0.65）。
- 份量與資源：上游作者在 4090 上微調約 1 小時；模型約 1800 萬參數，估計 3–8 GB 顯存（未實測）。
- 本機 `/home/oliver/CosyVoice` 已不存在，沒有 Fun-CosyVoice3 權重，所以 CosyVoice3 老師不在第一版。
- 可重用：faster-whisper 的 small、medium、large-v3 已在 HF 快取；`src/llm/text_normalizer.py` 有 OpenCC `s2twp`。
- 從 jetson-orin 可帶入並調整的：`tts_training_jobs.py`、`routes/tts_training.py`、`tools/tts-distill/`（`train_matcha.py`、`matcha_arch.py`、`export_matcha_onnx.py`、`lexicon_utils.py`、`audio_qc.py`、`distill_edge_teacher.py`）。`build_corpus.py` 依賴 main 沒有的 `lexicon-zh.txt`，需要改寫。

## 疊音與跳音診斷（2026-11-24）

- **疊音**：原因在 `zh-tw-hsiaochen-edge` 的聲學權重會重複音節（例如「去去法國」），base 權重搭同一份詞典就不會；jetson 原版的評比音檔中文 400 句有 42 句（10.5%）疊字。main 沒有程式修法，要重訓或重新蒸餾，用工單 11 的評量驗證。
- **跳音**：Matcha 沒有片段預取，片段之間有 221–280 ms 空白（Edge 約 20 ms），由工單 01 修正；是否就是聽到的跳音尚未用 WebRTC 擷取證實。
- 先前推測的「訓練時數字被丟掉造成錯位」沒有被這次診斷支持：疊字出現在一般詞語，不是數字。決定 7 的數字展開仍保留，因為文字與音檔不一致本身就會傷害訓練。

## 信任邊界與資料位置

- 所有新路由歸入 ADMIN（ADR 0021），登記在 `ROUTE_ACCESS`，並由 `tests/test_route_access.py` 守住。
- 同一時間只進行一件訓練工作；可取消，取消後釋放 GPU；日誌保留供介面顯示。
- 語料放 `data/tts/training/<slug>/`，匯出的聲線模型放 `models/tts/<slug>/`，並寫入 `voice.json` 的使用限制標示（沿用 `src/tts/voice_models.py` 的格式）。Edge 語料訓練出的模型不提供匯出（不能下載或複製出去）。
- 上傳檔案要檢查大小、格式與來源宣告；路徑由伺服器產生，不接受使用者提供的路徑。

## 驗收

- 「快速測試」用 Edge 老師完整跑一次：合成語料、品質檢查、訓練、匯出，聲線模型出現在清單並標示 Development only，可在數位人設定檔選用，舞台實際聽得到。
- 上傳自己的錄音（含自動產生的逐字稿並校對）完整跑一次，標示為 Research / Non-commercial。
- 有舞台連線或顯存不足時，按鈕停用且顯示原因；取消訓練後 GPU 顯存釋放。
- 跳音修正（工單 01）已在實機驗證；重訓後的聲線模型以工單 11 的評量，疊字句數不高於 base 的水準。
- `.github/workflows/ci.yml` 的每個步驟與現版主要基準全部通過，無新增失敗或跳過。

## 工單

- [01 修正跳音：Matcha 片段預取](issues/01-fix-overlap-and-skipping.md)
- [02 訓練環境實驗](issues/02-training-environment-spike.md)
- [03 訓練語料資料模型](issues/03-corpus-model.md)
- [04 Edge 測試用老師](issues/04-edge-test-teacher.md)
- [05 上傳錄音與逐字稿](issues/05-upload-and-transcripts.md)
- [06 訓練工作與匯出](issues/06-training-job-and-export.md)
- [07 介面原型](issues/07-ui-prototype.md)
- [08 訓練工作台介面](issues/08-training-ui.md)
- [09 notices 與文件](issues/09-notices-and-docs.md)
- [10 實機驗收](issues/10-live-acceptance.md)
- [11 疊字評量腳本](issues/11-repeated-syllable-benchmark.md)
