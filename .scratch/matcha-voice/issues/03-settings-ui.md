<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 設定介面
Status: resolved
Blocked by: 02

依[規格](../spec.md)第 6、7、11 點。

- 數位人設定檔編輯器：引擎多一個 Matcha 選項，選了之後出現聲線模型下拉選單；切換引擎時，不能把其他引擎的聲音帶過來（沿用 `switchTtsEngine` 的規則）。
- 在聲線模型名稱後面顯示使用限制標示（例如「Development only」），設定檔編輯器、角色組合、設定頁都要顯示。
- 介面說明寫出 hsiaochen-edge 的實測品質：中文 CER 13.2%、英文 WER 5.6%，以及 CPU 推理的特性。
- 補齊 zh-TW、zh-CN、en-US 三份 locales；前端測試 0 失敗、0 跳過。

## Comments

- 2026-11-24 實作（分支 `mv/03-settings-ui`）：
  - 測試接縫（TDD，未能事先與使用者確認，記錄於此）：`web/src/voiceSelection.js` 的公開函式（`switchTtsEngine`、`ttsVoiceProblem`、`voiceModelLabel`）；以記憶體渲染的 `AvatarProfileEditor`、`AvatarProfiles`（儲存前檢查）、`RoleComposition`、新元件 `VoiceModelCatalog`；三份 locales 的鍵一致。
  - 修正 02 留下的缺口：`switchTtsEngine` 切到 `matcha` 時清空 `ref_file`、`tts_server`、`model`，不帶入 Edge 聲線也不自動選聲線模型；從 Matcha 切到 BreezyVoice／Edge 也不留下聲線模型 ID。
  - 設定檔編輯器：引擎選單多 Matcha（標籤取自伺服器目錄 `Matcha-TTS (Research / Non-commercial)`）；選 Matcha 後出現「聲線模型」下拉選單，只列 `speech.tts.voice_models`（`/api/settings` 既有的 `speech_snapshot`，02 已提供），每項顯示「名稱 · 使用限制標示」；不顯示參考音檔、音訊庫與英文聲音欄位。
  - 儲存檢查：`referenceAudioProblem` 改名為 `ttsVoiceProblem(tts, voices, voiceModels)`，Matcha 未選或選了未列出的聲線模型時阻擋儲存並開啟「聲音」分頁（伺服器仍會再檢查）。
  - 角色組合：`Matcha-TTS · 曉臻（Edge 蒸餾） · Development only`；設定檔指到未列出的聲線模型時顯示「（未安裝的聲線模型）」。
  - 設定頁：「訪客互動與語音辨識」分頁的語音辨識卡片後新增「聲線模型（Matcha）」卡片（`VoiceModelCatalog.vue`），列出聲線模型、使用限制標示、語言、ID；沒有聲線模型時說明安裝方式（指向 `docs/voice-models.md`）。
  - 實測品質：hsiaochen-edge 的 CER 13.2%、WER 5.6%、暖機首音約 0.05 秒（CPU 4 條執行緒、未載入 MuseTalk）放在 `voiceSelection.js` 的 `MEASURED_VOICE_MODELS`，只對這個 ID 顯示；CPU 推理說明（sherpa-onnx、不佔 GPU、`matcha.num_threads` 預設 4）在設定檔編輯器與設定頁都顯示。文字在 `settings.voiceModels.*`（zh-TW、zh-CN、en-US）。
  - 未新增或修改路由，`ROUTE_ACCESS` 不變；未修改 Python。
  - CI：web lint、build 通過，`CI=1 npm test` 270 passed／0 failed／0 skipped（基準 261／0／0；Node 22）。Python：lock、ruff、pyright、check-integration 通過；pytest 2 failed／1562 passed／3 skipped，與基準相同（失敗為既有的 `test_real_pdf_pages_are_validated_rendered_and_released`、`test_greeting_only_profile_apply_keeps_playing_media_and_avoids_rebinding`）。
