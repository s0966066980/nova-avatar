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

- 2026-11-27：完成，`pyproject.toml` 的 import-linter 例外清單已全數刪除（5 份契約都沒有 `ignore_imports`）。
  - `src/llm`：新增 `reply_target.py` 的 `ReplyTarget` Protocol，取代對 `BaseAvatar` 的型別依賴；`base.py`、`service.py` 不再 import 渲染層。
  - `src/ragflow/settings.py`：`is_safe_avatar_id` 與 `AVATAR_ID_PATTERN` 移到 `src/utils/avatar_id.py`，`avatars.catalog` 重新匯出。
  - `src/asr/prewarm.py`：只剩 `prewarm_asr`；VAD 加辨識器的組合移到核心的 `src/server/speech_prewarm.py`（`app.py` 改呼叫它）。
  - `src/avatars/base.py`：`AudioTooLongError` 移到 `src/utils/audio_limits.py`，`vad.audio` 仍可匯入。
  - `src/config` 不再直接 import 各層的內部模組：各層提供 `config_api.py`（`src/tts`、`src/llm`、`src/avatars`），列出設定載入與寫入唯一可用的名稱。
- 與工單原文的差異：工單建議各層公開 `migrate_config(section)`／`validate_config(section)`。這裡用較小的做法：`config_api.py` 只重新匯出載入器原本就在呼叫的函式與常數，沒有改變任何驗證邏輯，因為統一的 section 介面要等工單 07 的契約模型才有型別可依。`src/greetings` 屬於核心，`config` 呼叫它不算越界。
- 舊的 `runtime_overrides.yaml` 載入與已移除引擎、欄位的相容處理沒有改動，既有測試通過。
- 新增 `tests/test_speech_prewarm.py`。
