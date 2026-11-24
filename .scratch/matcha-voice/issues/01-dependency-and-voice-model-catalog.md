<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 依賴與聲線模型清單
Status: ready-for-agent

依[規格](../spec.md)第 8、9 點與「使用限制」。

- 把 `sherpa-onnx` 放進 lock，並納入現版主要基準的安裝群組，更新 `uv.lock`。`uv lock --check` 和 `uv sync --frozen --check` 都要通過。
- 新增聲線模型清單：掃描 `models/tts/<id>/`，只列出結構完整的目錄。結構完整指：有模型檔、聲碼器、詞典和 tokens，加上一份使用限制標示（名稱、使用限制、支援語系、來源）。缺少標示或檔案不齊的目錄不列出，並在日誌說明原因。
- 為本機的 `models/tts/zh-tw-hsiaochen-edge/` 補上使用限制標示，標為 `Development only`。這個目錄在 gitignore 內，標示格式要寫進文件，標示檔本身不進 git。
- `matcha-icefall-zh-en`（base）沒有標示檔，所以不會被列出。
- 測試使用自足的 fixture，不依賴真實權重；0 失敗、0 跳過。
