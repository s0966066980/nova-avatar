<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# LLM 端點白名單
Status: ready-for-agent
Blocked by: 03

依[規格](../spec.md)「輸入限制原則」。數位人設定檔的 `llm.base_url` 只擋帳密／query／fragment（`src/profiles/store.py:66-72`），`profile_config`（`:81-89`）把伺服器 `api_key` 帶往該主機；`/api/profiles/greeting/preview`（`src/server/routes/profiles.py:130-138` → `src/greetings/content.py:87`）一個請求即可 SSRF 並送出 Bearer key。「是否為 Ollama」以 `"11434" in base_url` 判斷（`src/server/runtime_settings.py:866-867,940`）。

- 設定新增 `llm.endpoints: {名稱: {provider, base_url, api_key}}`（只能編輯設定檔）；預設由現有 `llm.base_url`/`api_key` 產生一個端點以維持相容。
- 數位人設定檔與控制台改存端點名稱；`store` 驗證名稱存在；舊設定檔的 `base_url` 在載入時對應到同值端點，對應不到則拒絕套用並提示。
- 問候預覽、模型列表與對話全走端點解析；金鑰只送往該端點的 `base_url`。
- 以明確 `provider` 取代 `"11434"` 子字串判斷。

完成：外部 `base_url` 的設定檔與問候預覽被拒、金鑰不外送的回歸測試；完整 CI 通過。

## Comments
