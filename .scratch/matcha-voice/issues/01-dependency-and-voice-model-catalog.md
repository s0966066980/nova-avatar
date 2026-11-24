<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 依賴與聲線模型清單
Status: resolved

依[規格](../spec.md)第 8、9 點與「使用限制」。

- 把 `sherpa-onnx` 放進 lock，並納入現版主要基準的安裝群組，更新 `uv.lock`。`uv lock --check` 和 `uv sync --frozen --check` 都要通過。
- 新增聲線模型清單：掃描 `models/tts/<id>/`，只列出結構完整的目錄。結構完整指：有模型檔、聲碼器、詞典和 tokens，加上一份使用限制標示（名稱、使用限制、支援語系、來源）。缺少標示或檔案不齊的目錄不列出，並在日誌說明原因。
- 為本機的 `models/tts/zh-tw-hsiaochen-edge/` 補上使用限制標示，標為 `Development only`。這個目錄在 gitignore 內，標示格式要寫進文件，標示檔本身不進 git。
- `matcha-icefall-zh-en`（base）沒有標示檔，所以不會被列出。
- 測試使用自足的 fixture，不依賴真實權重；0 失敗、0 跳過。

## Comments

- 2026-11-24 實作（分支 `mv/01-voice-model-catalog`，commit `468c577`）：
  - `pyproject.toml` 主要依賴加入 `sherpa-onnx==2.0.1`（2026-10-27 發布），`uv.lock` 只新增 `sherpa-onnx` 與 `sherpa-onnx-core`，torch／cu124 來源未動；`uv lock --check`、`uv sync --frozen --check` 通過。
  - 新增純模組 `src/tts/voice_models.py`：`list_voice_models(root=None)` 掃描 `models/tts/<id>/`，需有 `model.onnx`、`vocos-16khz-univ.onnx`、`lexicon.txt`、`tokens.txt` 與 `voice.json`；`phone/date/number-zh.fst` 存在時一併帶入。不完整、標示無效或 ID 不合法的目錄不列出並以 INFO 記錄原因；檔案與隱藏目錄略過。未新增路由。
  - 使用限制標示格式：`voice.json`（UTF-8 JSON 物件，`name`、`usage`、`languages`、`source` 皆必填；`usage` 只接受 `Development only` 或 `Research / Non-commercial`），格式寫在模組 docstring。
  - 測試 `tests/test_voice_models.py`（19 項，自足 fixture；含 `sherpa_onnx` 可匯入且為主要依賴，不 skip）。
  - 本機 `models/tts/zh-tw-hsiaochen-edge/voice.json`：worktree 隔離擋下寫入 worktree 外的路徑，內容已備於 scratchpad `matcha-voice/zh-tw-hsiaochen-edge.voice.json`，需由主線程複製；以真實檔案結構驗證：列出 hsiaochen-edge，`matcha-icefall-zh-en` 因無標示而不列出。
