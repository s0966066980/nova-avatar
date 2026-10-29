<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# TTS 與 LLM 授權標示
Status: ready-for-agent

依[規格](../spec.md)。2026-10-29 自原始來源查證：

- Fish-Speech／OpenAudio：2026-10-13 起 Community License，年營收 50 萬美元以下才可商用，整合方的客戶亦需符合，排除託管使用。
- IndexTTS2：bilibili 授權，月活 1 億或營收 10 億人民幣以下可商用，禁止用於改進其他模型，受中國法律管轄。
- XTTS-v2：CPML 非商用，Coqui 已不存在無法取得商用授權。
- Edge TTS：使用 Microsoft Edge 朗讀功能的非公開端點，無正式商用授權。
- Gemma 4 E2B：Apache-2.0（Gemma 使用條款不適用於 Gemma 4）。

比照 Wav2Lip 的「Research / Non-commercial」做法，在控制台引擎選單、`src/tts` 目錄資料與 `THIRD_PARTY_NOTICES.md` 標示限制；Edge TTS 標為「開發用」。加入 Gemma 4 聲明。更新 `tests/test_branding_compliance.py` 涵蓋新標示。

## Comments
