<!-- Copyright (c) 2026 HongXian0903 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Nova Avatar current-version test baseline

The release scope and acceptance rules are defined in
[`current-version-baseline.json`](current-version-baseline.json) and explained in
the [current-version testing guide](../docs/current-version-testing.md).
Use `scripts/check-current-version.py` in the prepared CUDA environment for the
primary local baseline. The GitHub GPU runner is a separate pending setup.

## Goals

1. The primary suite (`not live`) stays offline, deterministic, and self-contained.
2. Every collected test belongs to exactly one product area; an unclassified test
   module fails collection.
3. The primary baseline requires zero failures and zero skips. Missing GPU or
   required dependencies is a failure, not an accepted skip.
4. Live-service checks are explicit opt-ins and never silently call external
   services during the primary run.
5. Remove tests whose product contract is gone; preserve generic coverage with
   self-contained fixtures instead of dependencies on retired model files.

## Product areas

| Marker | Scope |
| --- | --- |
| `avatar` | MuseTalk transitions, mouth continuity, and rendering quality |
| `conversation` | Reply protocol, streaming, media fencing, playback, and voice sessions |
| `governance` | Branding, licensing, packaging, and integration audit contracts |
| `llm` | Model requests, profiles, normalization, and local llama.cpp lifecycle |
| `ragflow` | Optional RAGFlow deployment, settings, client, and turn integration |
| `runtime` | Server health, runtime settings, and optional dependency contracts |
| `speech` | ASR, VAD, TTS engines, and Edge TTS worker lifecycle |

`slow` is a manually maintained execution hint, not a complete duration budget.
`live` identifies checks that depend on this host: configured models, the installed
llama-server, and wall-clock budgets on its CPU.
These execution markers supplement, rather than replace, the product-area marker.

## Commands

```bash
# Prepared isolated CUDA environment, Node 22 on PATH; full local baseline
uv run --no-sync python scripts/check-current-version.py

# One primary product area
uv run --no-sync pytest -v -ra -m "speech and not live"
uv run --no-sync pytest -v -ra -m "conversation and not live"

# Primary Python regression only (the runner additionally rejects skips)
uv run --no-sync pytest -v -ra -m "not live"

# Explicit configured-model and installed-binary checks
NOVA_AVATAR_LIVE_LLM_CONTRACT=1 uv run --no-sync pytest -v -ra -m live
```

The local baseline records lock/environment checks, real CUDA tensor execution,
Ruff/Pyright/ESLint, offline integration, primary Python tests, frontend tests
with `CI=1`, and the production frontend build. Actual deployment-model GPU
inference and field audiovisual acceptance remain release checks; the local
baseline does not claim to execute them.

## Consolidation policy

Keep a separate module when it owns a distinct current product contract or has a
special execution boundary. Merge small modules only when the assertions and
ownership stay clear. File paths otherwise stay stable for linked design records.

Each rule has one owning test. A layer above the owner (job manager, HTTP route)
keeps only what it adds: the wiring and the status or message a failure maps to.
Route access is owned by `test_route_access.py`, which sweeps every route on the
real app; other modules assert only that their routes are declared `ADMIN`.

Shared fakes and fixtures live in the `*_fakes.py` and `access_helpers.py` helper
modules. A test module never imports another test module, so merging or deleting
one cannot break the rest.

## 測試放在哪裡

每個處理層自己擁有測試（ADR 0027）：`core/tests/`、`avatar/tests/`、
`services/stt/tests/`、`services/llm/tests/` 與 `services/tts/tests/`。測試只有在
除了 `nova_core.utils` 之外不需要核心任何東西時，才放進某一層的資料夾；凡是會建立
核心設定、驅動伺服器或串接多個層的測試（包含會載入核心設定的各層合約測試）都放在
`core/tests/`。本資料夾 `tests/` 只保留不屬於任何單一層的測試：品牌與授權稽核、
相依鎖定、啟動與權重腳本、ruff 安全規則，以及層級邊界設定。測試檔名在整個儲存庫內
保持唯一。

產品領域分類、`gpu`/`live`/`slow` 標記，以及測試不得寫入 `data/` 的規則都在根目錄的
`conftest.py`，因此適用於每個資料夾。測試資料夾沒有 `__init__.py`；`pyproject.toml`
的 `pythonpath` 把每個套件根目錄、測試資料夾與各層腳本資料夾放進 `sys.path`，所以
像 `llm_fakes` 這樣的輔助模組可在任何測試中直接以模組名稱匯入。
`uv run --no-sync pytest <資料夾>` 只執行單一資料夾。

Research and benchmark tools whose result is recorded in a ticket (local `.scratch/`, earlier ones in git history) are
deleted together with their tests once the decision has been applied.

An obsolete product contract need not be retained as an optional skip. For a
still-supported generic behavior, replace retired-model dependencies with a
self-contained fixture. Record the current contract or accepted ADR that
justifies a deletion; do not delete valid migration, security, or notice tests
because they contain an older name.
