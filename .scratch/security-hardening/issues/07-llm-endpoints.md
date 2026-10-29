<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# LLM 端點白名單
Status: resolved
Blocked by: 03

依[規格](../spec.md)「輸入限制原則」。數位人設定檔的 `llm.base_url` 只擋帳密／query／fragment（`src/profiles/store.py:66-72`），`profile_config`（`:81-89`）把伺服器 `api_key` 帶往該主機；`/api/profiles/greeting/preview`（`src/server/routes/profiles.py:130-138` → `src/greetings/content.py:87`）一個請求即可 SSRF 並送出 Bearer key。「是否為 Ollama」以 `"11434" in base_url` 判斷（`src/server/runtime_settings.py:866-867,940`）。

- 設定新增 `llm.endpoints: {名稱: {provider, base_url, api_key}}`（只能編輯設定檔）；預設由現有 `llm.base_url`/`api_key` 產生一個端點以維持相容。
- 數位人設定檔與控制台改存端點名稱；`store` 驗證名稱存在；舊設定檔的 `base_url` 在載入時對應到同值端點，對應不到則拒絕套用並提示。
- 問候預覽、模型列表與對話全走端點解析；金鑰只送往該端點的 `base_url`。
- 以明確 `provider` 取代 `"11434"` 子字串判斷。

完成：外部 `base_url` 的設定檔與問候預覽被拒、金鑰不外送的回歸測試；完整 CI 通過。

## Comments

### 2026-10-29 實作結果

- 新增 `src/llm/endpoints.py`：`llm.endpoints: {名稱: {provider, base_url, api_key}}` 只能於設定檔（建議 `config/config.yaml`）編輯；`provider` 必須明確為 `llamacpp`／`ollama`／`openai`，網址不得含帳密、query、fragment。未設定時由現有 `llm.provider`／`base_url`／`api_key` 產生一個以 provider 命名的端點（llama.cpp 使用 `llamacpp_host:port`），載入時凍結端點表；`runtime_overrides.yaml` 只保存所選端點名稱 `llm.endpoint`，不寫入端點表。
- 數位人設定檔 `llm` 改存 `endpoint` 名稱；`store.save` 驗證名稱存在，同時帶 `endpoint` 與 `base_url`／`provider` 會被拒。舊設定檔的 `base_url` 載入時對應到同網址端點並寫回；對應不到時名稱留空、磁碟不改寫並記錄警告，套用（`profile_config`）回 409 提示改選端點或於設定檔新增。
- `profile_config` 只從端點表一併設定 URL、provider 與金鑰，不再把任意 `llm` 欄位 `setattr`；問候預覽／試播、角色判斷與對話都經此解析。對話不再於無金鑰端點時改用 `DASHSCOPE_API_KEY`。
- 移除 `"11434"`／`"8080"` 子字串與 `is_ollama_endpoint` 推測；`/api/llm/model` 改收 `endpoint`；`/api/llm/models` 依各端點 provider 列模型，回應不含金鑰。控制台設定檔編輯器改為端點下拉選單並顯示唯讀網址。
- 以使用者實際 `config.yaml`＋`runtime_overrides.yaml` 與 `avatar_profiles.yaml` 副本驗證：兩份設定檔皆自動對應到 `llamacpp`（`http://127.0.0.1:8080/v1`），金鑰沿用，無需手動遷移。
- 回歸測試 `tests/test_llm_endpoints.py`（22 項）：外部 `base_url`／未列端點的設定檔儲存與問候預覽被拒且未建立任何 LLM 用戶端、金鑰只送往所選端點。CI：ruff、check-integration、pytest（849 通過；僅兩項已知 worktree 基線失敗）、web lint／test（200）／build 皆通過。

