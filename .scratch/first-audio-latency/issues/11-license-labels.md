<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# TTS 與 LLM 授權標示
Status: resolved

依[規格](../spec.md)。2026-10-29 自原始來源查證：

- Fish-Speech／OpenAudio：2026-10-13 起 Community License，年營收 50 萬美元以下才可商用，整合方的客戶亦需符合，排除託管使用。
- IndexTTS2：bilibili 授權，月活 1 億或營收 10 億人民幣以下可商用，禁止用於改進其他模型，受中國法律管轄。
- XTTS-v2：CPML 非商用，Coqui 已不存在無法取得商用授權。
- Edge TTS：使用 Microsoft Edge 朗讀功能的非公開端點，無正式商用授權。
- Gemma 4 E2B：Apache-2.0（Gemma 使用條款不適用於 Gemma 4）。

比照 Wav2Lip 的「Research / Non-commercial」做法，在控制台引擎選單、`src/tts` 目錄資料與 `THIRD_PARTY_NOTICES.md` 標示限制；Edge TTS 標為「開發用」。加入 Gemma 4 聲明。更新 `tests/test_branding_compliance.py` 涵蓋新標示。

## Comments

### 2026-10-30 實作結果

- TTS 引擎目錄（`src/server/runtime_settings.py` 的 `TTS_ENGINE_META`）比照 Wav2Lip 在名稱標示限制：`Edge TTS (Development only)`、`Fish Speech (Community License / Revenue < USD 500k)`、`IndexTTS2 (bilibili Model License / Usage thresholds)`、`XTTS (Research / Non-commercial)`；說明欄寫明條款（開發用、50 萬美元、月活／營收門檻、非商用）。
- `src/tts/engines/` 的 edge、fish、indextts2、xtts 檔頭加入使用分類註記。
- 控制台：TTS 選單 Edge 選項改為「Edge TTS (Development only) · 開發用」，選取時顯示開發用說明；角色設定檔的語音引擎選單改用伺服器目錄名稱（含限制），目錄無此引擎時顯示 ID。
- `THIRD_PARTY_NOTICES.md` 於 Optional TTS backends 下新增四個引擎小節，並新增 Gemma 4 語言模型小節（Apache-2.0，Gemma 使用條款不適用）；既有段落未改動。
- `docs/software-stack.md` 拆出受限 TTS 列並標 Edge TTS 為 Development only；`config/config_commercial.yaml` 註解改為 Edge TTS 僅供開發、商用前須替換。
- 測試：`tests/test_branding_compliance.py` 新增目錄、UI、引擎檔頭、notices、軟體組合檢查；`web/tests/tts-license-labels.test.js` 驗證角色引擎選單顯示限制標示。
- 驗證：ruff、pyright、check-integration 通過；pytest 1084 passed（排除兩項已知基準失敗）；前端 lint、207 項測試、build 通過。
- 待後續：商業審查設定檔仍預設 `edgetts`，待 BreezyVoice（issue 09）完成後改預設；README 的 TTS 說明留給 issue 14。
