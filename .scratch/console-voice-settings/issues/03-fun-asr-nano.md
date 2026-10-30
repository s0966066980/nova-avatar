<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# Fun-ASR-Nano-2512 取代 paraformer-zh
Status: ready-for-agent

依[規格](../spec.md)「語音辨識引擎」。調查摘要：Fun-ASR-Nano-2512（HF/ModelScope `FunAudioLLM/Fun-ASR-Nano-2512`，Apache-2.0，8 億參數，中文含方言、英文、日文，可中英混說，需 `trust_remote_code`）；輸出簡體，需 OpenCC `s2twp`。

- 下載腳本比照 `scripts/breezyvoice_weights.py`：釘 revision 與 sha256，放 `models/`。
- FunASR 引擎改載入此模型，遠端程式碼只允許釘住的版本；輸出轉繁體；中英文都接受（移除 `english_requires_whisper` 限制，若仍需要則說明）。
- 移除 `paraformer-zh` 與其下載／設定；`THIRD_PARTY_NOTICES.md` 加 Apache-2.0 聲明。
- `scripts/compare_asr.py` 支援新模型，GPU 實測交由 orchestrator（待實機驗證）；依結果在選單標「中英文」或「較慢」。

## Comments
