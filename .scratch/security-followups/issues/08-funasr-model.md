<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# FunASR `model_size` 接受任意字串
Status: resolved

STT 設定的 `model_size` 仍接受任意字串，FunASR 可能把它當成模型 ID 或本機路徑載入。依 [CODING_STANDARDS.md](../../../CODING_STANDARDS.md) 規則 1，改為只接受已知模型名稱或 `models/` 掃描結果，faster-whisper 同理。

## Comments
- 2026-11-27：FunASR 已在 `8c3afac` 移除。控制台儲存設定時，`core/nova_core/server/runtime_settings.py` 以 `STT_MODELS_BY_ENGINE` 白名單檢查 `model_size`，不在清單中就拒絕。尚未收緊的是設定檔（`config.yaml`／`runtime_overrides.yaml`）直接寫入的 `model_size`，它仍會交給 faster-whisper 當模型 ID 或路徑；這只有管理者能改，沒有請求欄位可以觸及。如果要連設定檔也限制，請另開工單。
