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
`live` identifies configured-model or installed llama-server environment checks.
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

An obsolete product contract need not be retained as an optional skip. For a
still-supported generic behavior, replace retired-model dependencies with a
self-contained fixture. Record the current contract or accepted ADR that
justifies a deletion; do not delete valid migration, security, or notice tests
because they contain an older name.
