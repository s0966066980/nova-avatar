<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 移除「語音辨識與合成」頁
Status: resolved
Blocked by: 01

依[規格](../spec.md)「移除語音辨識與合成頁」「預設聲音」。

- 語音辨識（引擎、模型、繁簡輸出）移到「訪客互動」頁並改名「訪客互動與語音辨識」。
- 移除全域 TTS 設定 UI；尚未套用設定檔時使用主數位人的聲音（後端：全域 TTS 由主數位人設定檔決定；舊的 `runtime_overrides.yaml` `tts` 區塊不再是第二個來源，處理方式與測試寫入 Comments）。
- 移除只為該頁存在的程式與測試；更新文件與控制台說明文字。

## Comments

### 2026-10-30 實作（分支 `cvs/02-remove-speech-tab`）

- 介面：「語音辨識與合成」頁移除；「訪客互動」改名「訪客互動與語音辨識」，新增「語音辨識」卡（引擎、模型、輸出字元集、預熱進度），本頁「儲存並套用」一併套用辨識草稿。表單只依 `GET /api/speech` 的 `stt.engines` 呈現：每個引擎項目新增 `models`、`output_scripts`（`{id, label}`）、`local_model_ready`，前端不再寫死 `funasr`；03 換引擎只需改後端 `STT_ENGINE_META`／`STT_MODELS_BY_ENGINE`。
- 移除全域 TTS：`POST /api/speech/tts`（路由、存取表、角色組合守門清單）、`ttsDraft`／`applyTtsSettings` 等前端狀態、全域上傳與刪除音檔、只供該頁的語系字串與原始碼比對測試。`speech_snapshot()["tts"]` 只剩引擎、音訊庫、模型與 Edge 聲線清單及 `notice`，不再回報全域聲線。已移除引擎的說明 `notice` 改顯示在設定檔「聲音與工具」，並在非啟動時套用設定檔成功後清除；所選引擎的目錄說明（Edge「開發用…無正式商用授權」）也顯示在該處，品牌稽核測試改檢查設定檔編輯器。
- 預設聲音（後端）：全域 `config.tts` 一律等於主數位人設定檔的 `tts`，只存在記憶體：
  - `app.main` 載入設定後讀 `config/avatar_profiles.yaml` 的主數位人聲音（`adopt_saved_main_voice`），Edge 預熱與 BreezyVoice 啟動因此用主數位人的聲音；檔案不存在或讀取失敗時暫用 `config.yaml` 並記 WARNING。
  - `initialize_roles` 在設定檔遷移後再採用一次，所以啟動套用失敗（`profiles_applied=False`）時新對話仍用主數位人的聲音；啟動時引擎相同，不再觸發 `apply_tts_settings` 試聽。
  - `RoleCoordinator.apply` 成功後把主數位人的聲音寫回 `state.config.tts`（同引擎換聲線也會更新）；換引擎時仍沿用 `apply_tts_settings` 驗證與試聽。
- 舊的 `runtime_overrides.yaml` `tts` 區塊：載入時忽略（記 INFO「tts 區塊已不再使用」），`persist_runtime_overrides` 不再寫 `tts`，下一次控制台儲存任何設定時整檔重寫即移除。現場檔的 `type: edgetts` 因此不再生效；現場兩個設定檔都是 Edge TTS，引擎不變，聲線改為主數位人設定檔的 `ref_file`。`config.yaml` 的 `tts` 只在第一次建立設定檔時成為主數位人的初始聲音。`pending_settings.json` 若留有舊的「語音合成」待套用項目，斷線套用時捨棄並記 WARNING，不阻擋其他待套用項目。
- 文件：README（預設聲音、已移除引擎說明位置）、`docs/idle-greetings.md` 設定頁表、`docs/project-status.md`、`config/config.yaml` 註解；對話面板的英文／Edge 錯誤提示改指向新位置。
- 測試：新增 `tests/test_default_voice.py`（覆蓋檔 `tts` 被忽略與移除、啟動採用主數位人聲音、啟動套用失敗仍用主數位人聲音、BreezyVoice 主數位人啟動不試聽、套用新聲線更新預設且不寫檔、舊待套用項目被捨棄）、STT 引擎資料與 TTS 快照測試、`/api/speech/tts` 已移除測試；前端以元件測試驗證新頁籤、依引擎資料切換模型與字元集、儲存本頁會套用辨識、Edge 限制說明。
- 結果：pytest 1334 passed、3 skipped（另 2 個已知 worktree 基線失敗未納入）；前端 217 passed；ruff、pyright、check-integration、`npm run lint`、`npm run build` 通過。

待實機驗證（需重建前端與重啟後端，交由 06）：
1. 主 checkout 合併後 `cd web && npm run build`，重啟後端；`grep "tts 區塊已不再使用" logs/nova-avatar_*.log` 應有一行（現場 `runtime_overrides.yaml` 仍有 `tts`）。
2. 控制台設定中心：側欄沒有「語音辨識與合成」，有「訪客互動與語音辨識」；頁內「語音辨識」卡選 FunASR 時出現輸出字元集，Whisper 時不出現；「套用語音辨識」成功。
3. 控制台任一設定儲存後，`config/runtime_overrides.yaml` 不再有 `tts:` 區塊。
4. 數位人設定檔把主數位人聲線改成 YunJhe 並儲存套用 → 新連線（舞台或控制台）說話為男聲；重啟後端後未套用前也一樣。

### 2026-10-30 實機驗證（orchestrator）
日誌出現「runtime_overrides.yaml 的 tts 區塊已不再使用：預設聲音改由主數位人設定檔決定」；兩句舞台語音（中、英）以主數位人的 Edge 聲音正常回覆。`min_silence_ms: 192` 已在執行設定生效。
