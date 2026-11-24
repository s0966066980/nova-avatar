<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# notices 與安裝文件
Status: resolved
Blocked by: 01

依[規格](../spec.md)「使用限制」與第 9 點。

- 在 `THIRD_PARTY_NOTICES.md` 新增以下條目：
  - sherpa-onnx（Apache-2.0）
  - base 模型：Research / Non-commercial，說明訓練資料未經查證
  - vocos 聲碼器
  - hsiaochen-edge：Development only，附 MSA §14(s)(iv) 的說明
- 新增安裝文件：聲線模型的目錄結構、使用限制標示的格式、手動複製步驟，以及檔案清單和 SHA-256。
- 更新 `docs/software-stack.md` 和 README（`docs/models.md` 只存在於 jetson-orin，不新建） 中的 TTS 支援清單。
- `scripts/check-integration.py`（品牌與來源稽核）必須通過。

## Comments

- 2026-11-24 實作（分支 `mv/04-notices-docs`）：
  - `THIRD_PARTY_NOTICES.md` 新增「Matcha voice models」：sherpa-onnx（Apache-2.0，`sherpa-onnx==2.0.1`）、base `dengcunqin/matcha_tts_zh_en_20251010`（**Research / Non-commercial**，訓練資料未經查證、可能含限非商用的 Baker 資料）、`vocos-16khz-univ.onnx`（倉庫標示 Apache-2.0、上游 Vocos 程式碼 MIT、Copyright (c) 2023 Charactr Inc.、權重訓練資料不明）、`zh-tw-hsiaochen-edge`（**Development only**，附 MSA §14(s)(iv) 原文）。明寫沒有任何聲線模型可商用；Matcha-TTS 程式碼未隨推理路徑出貨，第一階段不列。
  - 新增安裝文件 `docs/voice-models.md`：目錄結構、`voice.json` 格式（照 `src/tts/voice_models.py`，未改格式）、手動複製步驟、hsiaochen-edge 檔案清單與 SHA-256（含本機 `voice.json`）。
  - 更新 `docs/software-stack.md` 引擎表與 README（Matcha 為可選、Edge 仍是預設）。`docs/models.md` 在 main／`matcha-voice` 上不存在（只在 jetson-orin），未新建。
  - 稽核：`scripts/check-integration.py` 要求 notices 含 sherpa-onnx、base 模型、hsiaochen-edge 與 Development only，並把 `docs/voice-models.md` 列為必要文件；測試先紅後綠：`tests/test_branding_compliance.py`、`tests/test_integration_check.py`、`tests/test_voice_models.py`（文件中的 `voice.json` 範例須被清單接受、每個必要／選用檔案都有 SHA-256）。
  - 舊的 `NOTICE-NON-COMMERCIAL.txt` 寫 Research / Non-commercial，比 Development only 寬鬆；文件註明以 `voice.json` 為準，未改動模型目錄。
  - CI：lock、ruff、pyright、check-integration 通過；pytest 2 failed／1547 passed／3 skipped（基準 2／1543／3，失敗為既有的兩項）。
