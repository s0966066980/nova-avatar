<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# BreezyVoice 參考音檔選擇
Status: ready-for-agent

依[規格](../spec.md)「參考音檔」「開發用測試音檔」。

- 修正設定檔從 Edge 切到 BreezyVoice（及反向）時殘留另一種引擎的聲線值。
- 設定檔編輯器「聲音與工具」：BreezyVoice 時選單只列有逐字稿的參考音檔；未選擇時阻擋儲存並提示；音訊庫為空時提示並提供上傳入口（上傳附逐字稿、刪除、試聽）。
- 套用使用 BreezyVoice 的設定檔時自動啟動 BreezyVoice 伺服器（沿用全域頁既有流程）。
- 開發用測試音檔：提供可重複執行的匯入方式（腳本或後端啟動時不自動匯入，由管理者執行），把 `/tmp/claude-1000/-home-oliver-nova-avatar/f284899e-3e7d-40e8-bf07-77d0ecc09394/scratchpad/breezy-dev-prompt.wav` 與逐字稿「在密碼學中，加密是將明文資訊改變為難以讀取的密文內容，使之不可讀的方法。」以「BreezyVoice 測試音檔（僅開發用）」加入主 checkout 的 `data/voices/`；音訊庫支援「開發用」標記並在介面顯示「開發用，未取得說話者授權」。
- 測試：引擎切換、阻擋儲存、只列有逐字稿的音檔、開發用標記。

## Comments
