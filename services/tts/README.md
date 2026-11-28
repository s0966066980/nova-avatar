<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# nova-tts

語音合成處理層（ADR 0027）。Python 套件名稱是 `nova_tts`。

## 職責

- 把核心切好的可播回覆片段合成為 PCM，經 `SpeechChannel` 串流給核心；核心再把 PCM 交給數位人渲染，本層不持有渲染器。
- Edge 的重試與熔斷（`retry`、`edge_endpoint`）、預取與播放柵欄（`engines/prefetching`）。
- 聲音資產：參考音訊庫（`voice_library`）、Matcha 聲線模型（`voice_models`、`voice_preview`）、BreezyVoice 的 CosyVoice 伺服器（`cosyvoice_runtime`）。
- 聲線訓練（`training/`）：語料、逐字稿、自動辨識、訓練工作與匯出。顯存是否足夠由本層的 `training.gpu_guard` 檢查；舞台是否連線由核心檢查。

## 對外介面

- `nova_tts.adapter.create_tts_service(settings)`：回傳 `nova_contracts.tts.TtsService`（語音、音訊庫、聲線模型試聽，以及 `VoiceTraining` 的語料與訓練工作）。
- `nova_tts.config_section`：本層擁有的設定段落（`TTSConfig`、`MatchaConfig` 的欄位與預設值），以及核心的設定載入器用來遷移、驗證與建立 `TtsEngineSettings`、`TtsVoice` 的函式。新增引擎參數只改這裡。
- 其餘模組是內部實作，核心不得 import（import-linter 契約 `tts-internals-private`）。
- 型別與 loopback HTTP 形狀（拆成行程後使用）在 [`nova_contracts.tts`](../../contracts/README.md)。

## 引擎

| 引擎 | `tts.type` | 備註 |
|---|---|---|
| Edge TTS | `edgetts` | 雲端服務；預設，可選 zh-TW 與 en-US 聲音 |
| Matcha（聲線模型） | `matcha` | CPU 的 sherpa-onnx 執行；聲線模型由聲線訓練產生，權重放在 `models/` 之下 |
| BreezyVoice | `breezyvoice` | 選用，由本專案自己啟動的 CosyVoice 伺服器提供（需 `cosyvoice` conda 環境與 `services/tts/scripts/breezyvoice_weights.py` 下載的權重） |
| fake | `fake` | 只供測試與演練，輸出靜音 PCM，不出現在控制台 |

聲線、權重與雲端服務的授權各自獨立，不假設與根目錄的 Apache-2.0 相同；見 [`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md) 與 [`docs/guides/voice-models.md`](../../docs/guides/voice-models.md)。

## 依賴

`pyproject.toml` 宣告本層自己的第三方依賴，根專案以 path 依賴引用並共用根目錄的 `uv.lock`。本層 import `nova_core.utils`（日誌、路徑、音訊容器），但不宣告 `nova-core`，避免與核心對各層 adapter 的依賴形成循環。

## 測試

```bash
uv run --no-sync pytest services/tts
```

`services/tts/tests/` 放不需要核心的測試：聲線訓練各步驟、TTS 契約測試（`test_tts_contract.py`）、Edge 端點、聲線模型。需要核心設定或伺服器的測試（Matcha／BreezyVoice 引擎、Edge worker、聲線訓練路由、音訊庫路由）在 [`core/tests/`](../../core/README.md)。TTS 與訓練的假物件（`tts_fakes.py`、`edge_fakes.py`、`training_fakes.py`）放在本層的 `tests/`，核心的測試也會用到；它們是以 pytest 的 `pythonpath` 設定直接以模組名稱 import 的。

## 腳本

`services/tts/scripts/`：

| 腳本 | 用途 |
|---|---|
| `breezyvoice_weights.py` | 下載 BreezyVoice 與 g2pW 權重並以 SHA-256 驗證 |
| `breezyvoice_frontend.py` | BreezyVoice 的注音前端（由 CosyVoice 伺服器載入） |
| `cosyvoice_fastapi_server.py` | 自有 CosyVoice 伺服器（由 `nova_tts.cosyvoice_runtime` 啟動） |
| `setup-matcha-train.sh` | 建立聲線訓練用的獨立 venv（`.local/matcha-train`）與基底權重 |
| `matcha_base_weights.py`、`matcha_train_env_check.py` | 上一支腳本呼叫的基底權重下載與環境檢查 |
| `import-dev-voice.py` | 把開發用的參考錄音匯入音訊庫（標示「開發用，未取得說話者授權」） |
