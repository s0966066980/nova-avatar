<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# FunASR `model_size` 接受任意字串
Status: ready-for-agent

STT 設定的 `model_size` 仍接受任意字串，FunASR 可能把它當成模型 ID 或本機路徑載入。依 [CODING_STANDARDS.md](../../../CODING_STANDARDS.md) 規則 1，改為只接受已知模型名稱或 `models/` 掃描結果，faster-whisper 同理。

## Comments
