<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# nova-stt

語音轉文字處理層（ADR 0027）。Python 套件名稱是 `nova_stt`。

## 職責

把核心送來的一段語音轉成文字與語言；不持有任何對話狀態。語音活動偵測（VAD）與斷句不在這一層，由核心的 `nova_core.vad` 負責。

## 對外介面

- `nova_stt.adapter.create_stt_service(settings)`：回傳 `nova_contracts.stt.SttService`（`health`、`apply_engine`、`prepare`、`transcribe`）。同一行程內只載入一個辨識器，切換引擎時新引擎載入完成才取代舊的。
- `nova_stt.config_section`：本層擁有的 `asr` 設定段落（`ASRConfig` 的欄位與預設值），以及控制台的引擎目錄（`ENGINE_META`、`MODEL_SIZES`、`LANGUAGES`、`DEVICES`），新增 STT 引擎時在這裡加一筆；核心的設定載入器用來遷移與驗證它的函式也在這裡。
- 其餘模組（`base`、`factory`、`engines`）是內部實作，核心不得 import（import-linter 契約 `stt-internals-private`）。
- 型別與 loopback HTTP 形狀（拆成行程後使用）在 [`nova_contracts.stt`](../../contracts/README.md)。

## 引擎

| 引擎 | `asr.type` | 備註 |
|---|---|---|
| faster-whisper | `whisper` | 預設；權重與授權見 [`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md) |
| fake | `fake` | 只供測試，不出現在控制台的引擎清單；`asr.model_size` 當作要回傳的固定文字 |

Fun-ASR-Nano 已於 2026-11-26 移除，舊設定會自動改用 faster-whisper。

## 依賴

`pyproject.toml` 宣告本層自己的第三方依賴，根專案以 path 依賴引用並共用根目錄的 `uv.lock`。本層 import `nova_core.utils`（日誌、路徑），但不宣告 `nova-core`，避免與核心對各層 adapter 的依賴形成循環。

## 測試

```bash
uv run --no-sync pytest services/stt
```

`services/stt/tests/` 只放不需要核心的測試。需要核心設定的 STT 契約測試（`test_stt_contract.py`）在 [`core/tests/`](../../core/README.md)。

## 腳本

沒有本層專屬的 setup 或權重腳本。`small`、`turbo` 兩個尺寸優先使用 `models/whisper-small`、`models/whisper-large-v3-turbo`（存在 `model.bin` 時），否則由 faster-whisper 依尺寸名稱取得。
