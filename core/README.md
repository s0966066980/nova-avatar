<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# nova-core

核心（ADR 0027）。Python 套件名稱是 `nova_core`。核心持有所有輪次狀態，把 STT、LLM、TTS、數位人渲染四個處理層接成一場對話，並提供舞台與控制台使用的 HTTP 介面。

## 職責

| 子套件 | 內容 |
|---|---|
| `nova_core.server` | aiohttp 路由（`routes/`）、語音會話（`voice_session`）、回覆串流與切分（`reply_streaming/`）、對話與附件、全域狀態（`state`）、路由存取分類（`access`，ADR 0021） |
| `nova_core.vad` | 伺服器端語音活動偵測（Silero） |
| `nova_core.profiles` | 角色（人設）、組成、交接判斷的核心端、媒體、知識範圍 |
| `nova_core.config` | `config/config.yaml` 的載入、驗證、執行期覆寫；各層的設定段落由各層的 `config_section` 驗證 |
| `nova_core.greetings` | 閒置招呼的排程與預寫文案 |
| `nova_core.utils` | 各層共用的小工具（路徑、日誌、字素、音訊容器、計時）；它是葉節點，不得 import 任何處理層或核心的其他子套件 |

## 對外介面

- **HTTP**：每條路由屬於 public、stage（僅限 loopback）、admin（需登入）三類之一，分類見 `nova_core/server/access.py` 與 [ADR 0021](../docs/adr/0021-stage-local-console-login.md)。新增或修改路由前先讀 ADR 0021。
- **啟動入口**：`uv run python core/nova_core/server/app.py --config config/config.yaml`（`scripts/start-backend.sh`、`scripts/start-all.sh` 都這樣啟動）。
- **對處理層**：核心只經由各層的 `adapter` 與 `config_section` 使用該層（import-linter 契約 `*-internals-private`），型別來自 [`nova_contracts`](../contracts/README.md)。
- **對處理層提供**：只有 `nova_core.utils`。處理層 import 它，但因此各層的 `pyproject.toml` 不宣告 `nova-core`（核心已依賴各層的 adapter，雙向宣告會形成循環）。

## 測試

```bash
uv run --no-sync pytest core
```

`core/tests/` 放所有需要核心的測試：路由、輪次、插話、交接、設定、對話附件，以及用核心的設定（`nova_core.config`）或伺服器（`nova_core.server`）驅動某個處理層的契約測試（例如 STT／LLM／TTS 的契約測試），因為處理層的測試不得 import 核心。這些測試共用的假物件在 `core/tests/*_fakes.py` 與 `access_helpers.py`。

`core/tests/test_contracts.py` 同時檢查 `contracts/` 的規則，因為其中一個案例用核心的 `TurnContext` 建立 envelope；`contracts/` 本身沒有獨立的 `tests/`。

整個 repo 的 pytest 設定（marker、路徑）在根目錄的 `pyproject.toml` 與 `conftest.py`；沒有 GPU 也能全部通過，需要 GPU 的測試帶 `gpu` marker，預設排除。
