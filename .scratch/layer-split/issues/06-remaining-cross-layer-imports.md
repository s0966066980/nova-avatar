<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 清除其餘越界 import
Status: ready-for-agent
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
