<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 清除其餘越界 import
Status: resolved
Blocked by: 02, 03, 04, 05

依規格「現況」。

- `src/llm/base.py`、`src/llm/service.py`、`src/tts/base.py` 不再 import `BaseAvatar`。在工單 02、03 之後應該已經用不到，這裡確認並清掉。
- `src/ragflow/settings.py` import 了 `avatars.catalog.is_safe_avatar_id`。改成由核心驗證 avatar id 之後再傳入，或把這個純字串規則移到 `src/utils`。
- `src/asr/prewarm.py` import 了 `vad.factory`。預熱時需要 VAD 的話，由核心組合，STT 層不直接 import VAD。
- `src/config/loader.py`、`src/config/overrides.py` 伸進 tts、llm、greetings、avatars 的內部函式。每一層各自公開一個設定驗證與遷移的入口（例如 `migrate_config(section)`、`validate_config(section)`），config 只呼叫這些入口。
- 驗收：
  - import-linter 的例外清單清空；
  - 舊的 `runtime_overrides.yaml` 仍能載入，包括已移除引擎與欄位的相容處理；
  - CI 全部通過。

## Comments

### 2026-11-26 實作完成（分支 `ls/06-remaining-cross-layer-imports`）

- **處理層之間不再越界**：
  - `src/llm/service.py` 不再 import `BaseAvatar`。`llm_response` 等函式的參數改名為 `session`，型別是 LLM 層自己的 `ReplySession` Protocol（只要求 `sessionid` 與 `config`；輪次快照仍以 `getattr` 讀取，見下方「留給 07」）。`src/llm/base.py`、`src/tts/base.py` 在工單 02、03 之後已不 import `BaseAvatar`，這裡確認無誤。
  - `BaseLLM`、`OpenAILLM`、`create_llm_engine` 移除用不到的 `parent` 參數，LLM 引擎不再持有數位人物件。
  - avatar id 的純字串規則（`AVATAR_ID_PATTERN`、`is_safe_avatar_id`）搬到 `src/utils/avatar_ids.py`。`src/ragflow/settings.py` 與核心的 `src/server/routes/ragflow.py` 改從這裡 import；`src/avatars/catalog.py` 也從這裡 import，既有呼叫端照舊可用。
  - `src/asr/prewarm.py` 只剩 STT 自己的 `prewarm_recognizer(config)`（載入辨識器並推論一次，失敗就拋出）。先 VAD 後 STT 的組合搬到核心的 `src/server/speech_prewarm.py::prewarm_speech_input`，行為與記錄訊息不變；`src/server/app.py` 改呼叫它。
- **設定的入口**：每一層新增 `config_section.py`，`src/config/loader.py`、`src/config/overrides.py` 只呼叫這些入口：
  - STT（`src/asr/config_section.py`）：`migrate_config(asr)`，把已移除的 Fun-ASR 改成 faster-whisper `small`，並刪除 `output_script`。
  - LLM（`src/llm/config_section.py`）：`migrate_config(llm)` 刪除 `response_router`，並把舊的 `system_prompt` 搬進 `assistant_profile`；`validate_config(llm)` 固定端點表；`export_config(config)` 提供要寫回的 `reply_rules`。
  - TTS（`src/tts/config_section.py`）：`migrate_config(tts)` 刪除已移除引擎的欄位；`validate_config(matcha)` 檢查執行緒、顯存與 Whisper 模型；`migrate_voice_sources(tts, where=)` 在載入設定檔後把參考音訊搬進音訊庫。
  - 數位人渲染（`src/avatars/config_section.py`）：`migrate_config(model)` 刪除 ernerf、talkinggaussian、wav2lip 區塊；`export_config(model)` 提供要寫回的畫質參數（仍延後 import OpenCV）。
  - `src/greetings` 依規格屬於核心，`config` import `greetings.content` 是核心內部的呼叫，維持不變。
  - 資料類別（`src/config/schema.py`）仍由核心建立；搬移的是各層的遷移與驗證規則，錯誤訊息與警告文字不變。
- **例外清單**：刪除最後三條（`src.asr.prewarm -> src.vad.factory`、`src.llm.service -> src.avatars.base`、`src.ragflow.settings -> src.avatars.catalog`）。所有 contract 都已沒有 `ignore_imports`，`pyproject.toml` 的說明也一併更新。
- **測試**：新增 `tests/test_config_entry_points.py`：
  - 掃描 `src/config/*.py` 的 import，處理層只能經由 `config_section` 進入（修改前列出 5 處越界）。
  - 舊的 `runtime_overrides.yaml` 同時帶有 Fun-ASR 與 `output_script`、`response_router`、只有 `system_prompt`、ernerf／talkinggaussian／wav2lip 區塊、`tts` 區塊，加上設定檔中已移除的 TTS 欄位，仍能載入成目前的設定。
  - 既有的相容測試（Fun-ASR、已移除的 TTS 引擎與欄位、wav2lip 區塊、Matcha 限制、assistant_profile 往返）都沒有修改，照常通過。
  - 既有測試只調整兩處：`BoardLLM(config, parent=avatar)` 改為 `BoardLLM(config)`；WebRTC 生命週期測試的假 LLM 不再帶 `parent`。
- **驗證**：`uv lock --check`、`ruff check .`、`pyright`（0 errors）、`lint-imports`（7 kept，沒有任何例外）、`scripts/check-integration.py`、`pytest`（2233 passed、2 skipped），以及 `web` 的 lint、test、build，全部通過。
- **留給 07**：
  - 核心仍以數位人物件傳遞 LLM 的輪次狀態：`voice_session` 寫入 `_reply_rules_snapshot`、`_assistant_profile_snapshot`、`_reply_mode_callback`、`_incremental_board`，`llm_response` 再讀出來。這些狀態不會讓 `llm.service` import 數位人，所以本工單沒有處理；07 定義 LLM 介面時，可以改成明確的參數。
  - 核心直接 import 處理層內部模組的完整清單，見工單 07 的交接筆記。
- **待維護者實機確認**：啟動時的語音輸入預熱改由核心組合。請以 `app.prewarm: true`、`vad.enabled: true` 啟動後端，確認啟動日誌 `Startup prewarm:` 中的 `speech_input` 為 `True`，且第一次免按對話沒有額外的辨識器載入延遲。
