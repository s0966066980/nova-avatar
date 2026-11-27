<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# nova-render

數位人渲染層（ADR 0027）。Python 套件名稱是 `nova_render`，內含 `musetalk`（MuseTalk 整合）與 `scene`（舞台背景與綠幕合成）。

與 STT、LLM、TTS 不同，渲染留在核心行程內，只以程式介面隔開（`nova_contracts.avatar`，沒有 loopback HTTP）。

## 職責

- 依核心交來的 TTS PCM 逐格產生嘴型畫面與影像輸出（`base`、`audio_stream_handler`、`video_output`）；本層不持有 TTS。
- 模型載入與換人物（`factory`、`builder`）、人物素材目錄與匯入（`catalog`、`asset_io`）、嘴型畫質（`mouth_quality`）。
- 舞台場景：背景圖片／影片的解碼、綠幕去背與合成、角色呈現（`scene.service`、`scene.role_presentation`）。

## 對外介面

- `nova_render.adapter.create_avatar_service()`：回傳 `nova_contracts.avatar.AvatarService`；每場對話的渲染器是 `AvatarRenderer`。
- `nova_render.config_section`：核心的設定載入器用它遷移與匯出 `model` 設定段落。
- 其餘模組是內部實作，核心不得 import（import-linter 契約 `avatar-internals-private`）。
- 型別在 [`nova_contracts.avatar`](../contracts/README.md)。

## 引擎

| 引擎 | `model.type` | 備註 |
|---|---|---|
| MuseTalk | `musetalk` | 授權為 MIT（Tencent Music Entertainment Group 著作權）；模型與相依套件各有授權，見 [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) |
| fake | `fake` | 只供測試，輸出固定畫面，不出現在控制台 |

Wav2Lip 整合已於 2026-11-24 移除、不再內建；它的上游程式與權重屬 **Research / Non-commercial**，不得進入商用發行版，細節見 `THIRD_PARTY_NOTICES.md`。

`nova_render/musetalk/` 帶著自己的 `pyproject.toml`（套件 `nova-avatar-musetalk`，OpenMMLab 等重型依賴），由 `nova-render` 的 `musetalk` extra 引用；其中 `utils/`、`whisper/` 是 MuseTalk 上游衍生程式，保留各檔的上游授權標示與 `Modified by HongXian0903, 2026`。

## 依賴

`pyproject.toml` 宣告本層自己的第三方依賴與 extra（`musetalk`、`tensorrt`），根專案以 path 依賴引用並共用根目錄的 `uv.lock`。本層 import `nova_core.utils`（日誌、路徑），但不宣告 `nova-core`，避免與核心對各層 adapter 的依賴形成循環。

## 測試

```bash
uv run --no-sync pytest avatar
```

`avatar/tests/` 放不需要核心的測試（安全載入、嘴型連續性、MuseTalk 前處理）。需要核心設定或伺服器的測試（人物匯入、場景背景、媒體柵欄、嘴型畫質、即時渲染）在 [`core/tests/`](../core/README.md)。

## 腳本

`avatar/scripts/`：

| 腳本 | 用途 |
|---|---|
| `download_musetalk_weights.sh` | 下載 MuseTalk 權重並驗證（清單與雜湊在根目錄 `scripts/musetalk_weights.py`，因 TTS 的權重腳本也共用其中的驗證函式） |
| `post_musetalk_install.sh` | 安裝 MuseTalk 之後修補專案 venv 的 mmdet 版本檢查 |
| `setup-tensorrt.sh`、`build-musetalk-tensorrt.py`、`verify-musetalk-tensorrt.py` | 建置與驗證 TensorRT 引擎 |
| `benchmark-compositor.py` | 綠幕合成的效能比較 |
