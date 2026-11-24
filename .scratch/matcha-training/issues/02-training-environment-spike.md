<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 訓練環境實驗
Status: ready-for-agent

依[規格](../spec.md)第 8 點。

- 在 `.local/matcha-train/` 建立獨立 venv，不改主程式 `.venv`；先試上游 `matcha-tts`（PyPI，cp310），失敗再試 CosyVoice 內附的 `third_party/Matcha-TTS`。
- 從 ModelScope `dengcunqin/matcha_tts_zh_en_20251010` 下載 `pytorch_model_sherpa.bin`（約 75 MB）到 `.local/matcha-base/`，記錄 SHA-256 與授權欄原文。
- 驗證能嚴格載入權重，並用幾筆假資料在 CPU 跑一個訓練步驟；不要使用 GPU，也不要啟動伺服器。
- 結果寫在本工單 Comments：選用的來源、版本、依賴清單與授權、安裝與載入的實際指令。無法嚴格載入時，說明差異並提出替代做法，不要自行放寬載入檢查。
