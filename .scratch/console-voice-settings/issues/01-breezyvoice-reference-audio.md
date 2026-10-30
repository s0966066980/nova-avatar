<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# BreezyVoice 參考音檔選擇
Status: resolved

依[規格](../spec.md)「參考音檔」「開發用測試音檔」。

- 修正設定檔從 Edge 切到 BreezyVoice（及反向）時殘留另一種引擎的聲線值。
- 設定檔編輯器「聲音與工具」：BreezyVoice 時選單只列有逐字稿的參考音檔；未選擇時阻擋儲存並提示；音訊庫為空時提示並提供上傳入口（上傳附逐字稿、刪除、試聽）。
- 套用使用 BreezyVoice 的設定檔時自動啟動 BreezyVoice 伺服器（沿用全域頁既有流程）。
- 開發用測試音檔：提供可重複執行的匯入方式（腳本或後端啟動時不自動匯入，由管理者執行），把 `/tmp/claude-1000/-home-oliver-nova-avatar/f284899e-3e7d-40e8-bf07-77d0ecc09394/scratchpad/breezy-dev-prompt.wav` 與逐字稿「在密碼學中，加密是將明文資訊改變為難以讀取的密文內容，使之不可讀的方法。」以「BreezyVoice 測試音檔（僅開發用）」加入主 checkout 的 `data/voices/`；音訊庫支援「開發用」標記並在介面顯示「開發用，未取得說話者授權」。
- 測試：引擎切換、阻擋儲存、只列有逐字稿的音檔、開發用標記。

## Comments

### 2026-10-30 實作（分支 `cvs/01-breezyvoice-reference-audio`）

- 引擎切換：`web/src/voiceSelection.js` 的 `switchTtsEngine`；切到 BreezyVoice 清空聲線且不自動選音檔，切回 Edge 改為 `zh-TW-HsiaoChenNeural` 並清掉逐字稿、服務網址與模型。編輯器改用 `@change`，切換設定檔不會誤清。
- 聲音與工具：BreezyVoice 選單只列有逐字稿的音檔（開發用音檔附標示），下方顯示所選音檔的逐字稿；未選或選到不可用的音檔時顯示提示，「僅儲存草稿／儲存並套用」會被擋下，並切到該設定檔的聲音分頁。設定檔層級的逐字稿欄位已移除，改用音訊庫的逐字稿（選新音檔時清掉舊的覆寫值）。後端 `ProfileStore.save` 同樣要求 BreezyVoice 有參考音檔與逐字稿（載入舊設定不受影響）。
- 音訊庫：新的可重用元件 `VoiceLibraryManager.vue`（上傳附必填逐字稿、試聽、二次確認刪除、開發用標示、空庫提示），放在設定檔編輯器裡。新路由 `GET /api/speech/voices/{voice_id}/audio`（admin，只接受音訊庫 ID）供試聽。全域頁上傳後選取新音檔的動作移回 `SettingsPanel.vue`，composable 不再改全域草稿；02 移除全域頁時可直接刪掉這段。
- 套用：設定檔使用 BreezyVoice 且引擎沒變時，`RoleCoordinator.apply` 會依設定檔的模型與服務網址呼叫 `ensure_server`（有連線時略過，以免中斷進行中的對話）；引擎改變時沿用 `apply_tts_settings`。啟動失敗回傳 503。
- 開發用測試音檔：`scripts/import-dev-voice.py <錄音> [--voices-dir …]`，預設名稱與逐字稿即本票指定的內容；音訊庫記錄加上 `development: true`。已匯入主 checkout：`data/voices/c0a7e758a35aa1bc.wav`（7.9 秒），重複執行顯示「已存在」。
- 測試：pytest 1340 passed（僅 2 個已知 worktree 基線失敗）；前端 216 passed；ruff、pyright、check-integration、`npm run lint`、`npm run build` 通過。

待實機驗證（需 GPU 與重啟，交由 06）：
1. 主 checkout 合併後重建前端並重啟後端，登入控制台 →「數位人、AI 與知識設定」→ 任一設定檔 →「聲音與工具」，引擎改 BreezyVoice：選單只有「BreezyVoice 測試音檔（僅開發用）（7.9 秒） · 開發用，未取得說話者授權」，未選時儲存被擋。
2. 音訊庫按「試聽」可播放錄音；選取後「儲存並套用」（無連線時）→ `logs/cosyvoice-server.log` 出現啟動紀錄，`curl -s http://127.0.0.1:50000/health` 回應正常。
3. 舞台或控制台對話一輪，BreezyVoice 正常發聲。

### 2026-10-30 實機驗證（orchestrator）
整合分支 6965222 啟動：開發用測試音檔已在 `data/voices/`；兩個設定檔殘留的 `ref_text` 已自動移除並記錄。使用者決定預設繼續用 Edge TTS，BreezyVoice 試聽的實機操作略過（BreezyVoice GPU 合成已在 first-audio-latency 評比驗證；CPU 實測一句約 20–29 s，不可用）。
