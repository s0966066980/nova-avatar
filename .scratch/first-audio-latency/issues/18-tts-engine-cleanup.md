<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 只保留 BreezyVoice 與 Edge TTS
Status: ready-for-agent

依[規格](../spec.md)「最終決定」：TTS 只保留 BreezyVoice（`breezyvoice`）與 Edge TTS（`edgetts`），其餘引擎全部移除：CosyVoice／Fun-CosyVoice3（`cosyvoice`、`fun-cosyvoice3`）、Fish（`fishtts`）、GPT-SoVITS（`gpt-sovits`）、IndexTTS2（`indextts2`）、XTTS（`xtts`）。

- 移除引擎程式、設定選項、控制台選單、音訊庫中的引擎特有欄位、啟動腳本中只為這些引擎存在的部分、測試、文件與授權標示中僅屬於這些引擎的段落。
- BreezyVoice 以 CosyVoice v1 為基礎、經 `scripts/cosyvoice_fastapi_server.py` 載入：保留它需要的伺服器與上游 CosyVoice 程式碼、版權與 `THIRD_PARTY_NOTICES` 中 BreezyVoice 依賴的部分；伺服器只保留 BreezyVoice 路徑。
- 既有設定或音訊庫指到已移除的引擎時：啟動不失敗，改回 Edge TTS 並在日誌與控制台說明（與既有「已移除引擎」處理一致，參考 `tests/test_runtime_settings.py::test_removed_qwen_speech_engines_are_rejected`）。
- `scripts/tts_bakeoff.py` 只保留 BreezyVoice。
- repo 外的權重與環境不刪，盤點後列給使用者決定。

## Comments
