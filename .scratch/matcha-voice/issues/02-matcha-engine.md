<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# Matcha 引擎與設定檔整合
Status: resolved
Blocked by: 01

依[規格](../spec.md)第 6、10、11 點與「第一階段範圍」。

- 移植 jetson-orin 的 `src/tts/engines/matcha.py` 和 `src/tts/pcm_emitter.py`（`git show origin/jetson-orin:<path>`），並照 AGENTS.md 加上來源和修改標示。
- 在 factory、`engines/__init__` 和 `voice_library.TTS_ENGINES` 註冊 `matcha`。數位人設定檔驗證要接受 `matcha`，並要求選定一個已列出的聲線模型。zh-TW 和 en-US 都用這個聲線模型。
- `num_threads` 改為全域伺服器設定，預設 4。`length_scale` 和 `noise_scale` 固定用預設值。
- 設定檔指到的聲線模型不存在時，處理方式跟 BreezyVoice 缺少參考音檔時一致，要明確提示，不能默默改用其他聲音。
- 移植並調整 `tests/test_matcha_tts.py`，納入主要基準；0 失敗、0 跳過。
- 新增或調整的路由列入 `ROUTE_ACCESS`（ADR 0021）。
- 應用日誌要輸出 `first audio:`，格式跟其他引擎一致，供 05 驗收使用。

## Comments

- 2026-11-24 實作（分支 `mv/02-matcha-engine`）：
  - 測試接縫（TDD，未能事先與使用者確認，記錄於此）：`create_tts_engine("matcha", …)` 的 `txt_to_audio`（假 `sherpa_onnx` 模組＋fixture 聲線模型，`model.onnx` 是手工編碼、帶 `model_type` metadata 的極小 ONNX）、`normalize_matcha_text`、`dict_to_config`、`ProfileStore` 儲存與載入、`speech_snapshot`／`preview_profile_voice`、`check_language_support`。`tests/test_matcha_tts.py` 15 項，不載入真實權重、不 skip；jetson 的 live 測試（會 skip）不移植。
  - 聲線模型 ID 放在既有的 `tts.ref_file`，不新增欄位：`ref_file` 在各引擎都代表「用哪個聲音」（Edge 聲線名稱、BreezyVoice 音訊庫 ID），聲線模型就是 Matcha 的聲音；`model` 是 BreezyVoice 權重目錄，綁在 cosyvoice 伺服器身分與 `check_model` 上，不適合。`voice_library.check_reference` 對 `VOICE_MODEL_ENGINES = {"matcha"}` 只接受 `list_voice_models()` 列出的 ID；`voice_en_us` 對 Matcha 無作用（同一聲線模型說中英文），`check_language_support` 改用 `ENGLISH_TTS_ENGINES = {"edgetts", "matcha"}`。
  - `num_threads`：新增頂層 `matcha.num_threads`（`MatchaConfig`，預設 4，1–64 整數，載入時驗證），寫在 `config/config.yaml`；不在 `TTSConfig`，因為 `profile_config` 會整個換掉 `tts`。目前不開放在控制台修改。`length_scale=1.0`、`noise_scale=0.667` 為模組常數。
  - 聲線模型缺失（比照 BreezyVoice 缺參考音檔）：儲存設定檔時未選或不在清單中 → `ProfileError`；套用／試聽 → `SettingsError`；載入時已存的 ID 不在清單 → 清空並記 WARNING（指出 ID 與修復方式），引擎仍是 `matcha`；引擎建立不會失敗，但每個片段都以明確訊息失敗（`tts_exhausted_before_audio`、例外往上拋，試聽顯示訊息），絕不改用其他聲音。
  - 引擎：用 onnxruntime 讀 `model_type`（非 `matcha-tts` 拒絕），先 `config.validate()` 再建 `OfflineTts`（sherpa-onnx 遇無效設定會結束行程）；已載入的聲線模型依（聲線模型, 執行緒數）在行程內共用，角色與連線不重複載入。日誌 `matcha first audio:%.4fs`。`synthesize_fragment` 在 main 沒有呼叫者，未移植；`avatars/base.py` 的 `np.clip` 未移植（Matcha 輸出已限制峰值 0.88）。
  - 伺服器選項：`TTS_ENGINE_META` 新增 `matcha`（`Matcha-TTS (Research / Non-commercial)`），`speech_snapshot()["tts"]["voice_models"]` 列出聲線模型與使用限制標示，供 03 使用。未新增路由，`ROUTE_ACCESS` 不變。
  - 待 03：現有 `web/src/voiceSelection.js` 的 `switchTtsEngine` 切到 matcha 時會填入 Edge 預設聲線，儲存會被拒絕（明確錯誤），需由 03 改為選聲線模型。
  - 以真實 hsiaochen-edge 在 CPU 做一次性手動檢查（非測試）：載入約 1.0 s，暖機首音 0.04–0.06 s，中英文皆有輸出。
- 2026-11-24 審查修正（分支 `mv/review-fixes`）：載入／遷移時聲線模型 ID 只檢查格式（`VOICE_MODEL_ID`），不在清單中的 ID 保留、不再清空寫回，`ProfileStore.load()` 不因聲線模型目錄被刪除或改名而失敗；格式不正確才清空並記 WARNING。是否已安裝改由 `check_voice_model_installed` 在儲存設定檔（`require_voice`）、套用與試聽時檢查，錯誤訊息指出缺少的聲線模型 ID。合成時的行為不變。BreezyVoice 不受影響。
