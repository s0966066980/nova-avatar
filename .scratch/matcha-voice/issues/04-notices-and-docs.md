<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# notices 與安裝文件
Status: ready-for-agent
Blocked by: 01

依[規格](../spec.md)「使用限制」與第 9 點。

- 在 `THIRD_PARTY_NOTICES.md` 新增以下條目：
  - sherpa-onnx（Apache-2.0）
  - base 模型：Research / Non-commercial，說明訓練資料未經查證
  - vocos 聲碼器
  - hsiaochen-edge：Development only，附 MSA §14(s)(iv) 的說明
- 新增安裝文件：聲線模型的目錄結構、使用限制標示的格式、手動複製步驟，以及檔案清單和 SHA-256。
- 更新 `docs/software-stack.md`、`docs/models.md` 和 README 中的 TTS 支援清單。
- `scripts/check-integration.py`（品牌與來源稽核）必須通過。
