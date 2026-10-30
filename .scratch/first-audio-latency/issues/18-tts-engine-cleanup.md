<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 只保留 BreezyVoice 與 Edge TTS
Status: resolved

依[規格](../spec.md)「最終決定」：TTS 只保留 BreezyVoice（`breezyvoice`）與 Edge TTS（`edgetts`），其餘引擎全部移除：CosyVoice／Fun-CosyVoice3（`cosyvoice`、`fun-cosyvoice3`）、Fish（`fishtts`）、GPT-SoVITS（`gpt-sovits`）、IndexTTS2（`indextts2`）、XTTS（`xtts`）。

- 移除引擎程式、設定選項、控制台選單、音訊庫中的引擎特有欄位、啟動腳本中只為這些引擎存在的部分、測試、文件與授權標示中僅屬於這些引擎的段落。
- BreezyVoice 以 CosyVoice v1 為基礎、經 `scripts/cosyvoice_fastapi_server.py` 載入：保留它需要的伺服器與上游 CosyVoice 程式碼、版權與 `THIRD_PARTY_NOTICES` 中 BreezyVoice 依賴的部分；伺服器只保留 BreezyVoice 路徑。
- 既有設定或音訊庫指到已移除的引擎時：啟動不失敗，改回 Edge TTS 並在日誌與控制台說明（與既有「已移除引擎」處理一致，參考 `tests/test_runtime_settings.py::test_removed_qwen_speech_engines_are_rejected`）。
- `scripts/tts_bakeoff.py` 只保留 BreezyVoice。
- repo 外的權重與環境不刪，盤點後列給使用者決定。

## Comments

### 2026-10-30 實作（分支 `fal/18-tts-cleanup`）

**移除**：`src/tts/engines/{cosyvoice,fish,sovits,indextts2,xtts}.py` 與其專屬測試；工廠、`TTS_ENGINE_META`、
控制台與數位人設定檔選單只剩 `edgetts`、`breezyvoice`。原 `CosyVoiceTTS` 的 HTTP 串流用戶端併入
`src/tts/engines/breezyvoice.py`（只發 zero-shot；檔頭改為繼承來源＋`Modified by HongXian0903, 2026`）。
`TTSConfig` 與控制台刪掉僅屬已移除引擎的 `mode`、`language`、`speaker`、`instruct`、`device`；
`tts_server` 預設由 GPT-SoVITS 的 9880 改為空白（BreezyVoice 用 50000）。

**保留給 BreezyVoice**：`scripts/cosyvoice_fastapi_server.py` 只留 BreezyVoice 載入與 `/inference_zero_shot`
（拿掉 AutoModel、cross-lingual、instruct2 與 CosyVoice 2/3 家族判斷）；`cosyvoice_runtime.py` 只掃
`cosyvoice.yaml`＋`word_utils.py` 的資料夾，預設 `models/BreezyVoice`；`~/CosyVoice` 程式碼與 conda 環境
`cosyvoice` 照舊。`THIRD_PARTY_NOTICES.md` 刪 Fish／IndexTTS2／XTTS 段，補 CosyVoice（Apache-2.0，Alibaba／
FunAudioLLM，外部 checkout、不隨附）；`docs/software-stack.md`、README、ADR 0006、設定檔註解同步。
`scripts/tts_bakeoff.py` 只剩 BreezyVoice（`--engine` 改為選填的執行名稱）。

**已存設定指到已移除引擎**：`config.yaml`／`runtime_overrides.yaml`／`avatar_profiles.yaml` 載入時改用
Edge TTS（`zh-TW-HsiaoChenNeural`），清掉參考音訊、逐字稿、模型與服務網址，舊欄位直接略過，不會啟動失敗；
日誌記 WARNING，控制台「語音」設定顯示同一段說明，成功套用 TTS 後消失。數位人設定檔會存回移除後的內容；
儲存新設定檔時指定已移除引擎則拒絕。測試：`tests/test_tts_engine_cleanup.py`（18 項）。
主 checkout 現行 `runtime_overrides.yaml` 與 `avatar_profiles.yaml` 已是 `edgetts`，合併後只會略過
`mode`、`speaker` 等舊欄位（設定檔會存回），不出現提示。

**驗證**：`pytest` 1319 passed、2 failed（已知 worktree 基準失敗）、3 skipped；`ruff`、`pyright`、
`scripts/check-integration.py` 通過；web `lint`／`test`（209）／`build` 通過。

**repo 外的已移除引擎資產（未刪除，請使用者決定）**：

| 項目 | 大小 | 說明 |
|---|---|---|
| `~/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B-2512` | 19 GB | Fun-CosyVoice3 權重，可刪 |
| `~/CosyVoice/pretrained_models/CosyVoice2-0.5B` | 9.1 GB | CosyVoice 2 權重，可刪 |
| `~/.cache/modelscope/hub/iic/CosyVoice2-0___5B` | 4.8 GB | CosyVoice 2 的 ModelScope 快取，可刪 |
| `~/.cache/huggingface/hub/models--FunAudioLLM--CosyVoice2-0.5B` | 12 KB | 空殼快取，可刪 |
| `~/.cache/huggingface/hub/models--Qwen--Qwen3-TTS-12Hz-1.7B-Base`、`…-0.6B-CustomVoice` | 4.3 GB、2.4 GB | 先前已移除的 Qwen3-TTS，可刪 |
| `/home/oliver/nova-avatar/.scratch/first-audio-latency/tts-bakeoff/runs/cosyvoice3` | 91 MB | 評比音檔（git 忽略），可刪 |
| `~/CosyVoice`（不含權重 74 MB）、conda 環境 `cosyvoice`（18 GB） | — | **BreezyVoice 仍需要，勿刪** |
| `~/.cache/modelscope/hub/pengzhendong/wetext` | 52 MB | CosyVoice 前端可能載入，建議保留 |

找不到 GPT-SoVITS、Fish Speech、IndexTTS2、XTTS 的模型資料夾、conda／venv 環境或 Docker 映像。
