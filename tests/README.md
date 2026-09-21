<!-- Copyright (c) 2026 HongXian0903 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Nova Avatar test suites

The test suite is organized by product area through markers in `conftest.py`.
File paths stay stable because design records and incident notes link directly to
individual regression tests.

## Goals

1. The default suite stays offline, deterministic, and safe to run on every change.
2. Every collected test belongs to exactly one product area; an unclassified test
   module fails collection.
3. The quick suite gives fast local feedback while the full suite remains the
   handoff gate.
4. Live-service checks are explicit opt-ins and never silently call external
   services during the default run.
5. Tests are removed only when their product contract is gone or equivalent
   coverage is proven. File age alone is not a deletion criterion.

## Product areas

| Marker | Scope |
| --- | --- |
| `avatar` | MuseTalk transitions, mouth continuity, and rendering quality |
| `conversation` | Reply protocol, streaming, media fencing, playback, and voice sessions |
| `governance` | Branding, licensing, packaging, and integration audit contracts |
| `llm` | Model routing, profiles, normalization, and local llama.cpp lifecycle |
| `ragflow` | Optional RAGFlow deployment, settings, client, and turn integration |
| `runtime` | Server health, runtime settings, and optional dependency contracts |
| `speech` | ASR, VAD, TTS engines, and Edge TTS worker lifecycle |

`slow` identifies deterministic tests whose normal duration exceeds roughly one
second. `live` identifies tests that require an explicitly enabled external model.
These execution markers supplement, rather than replace, the product-area marker.

## Commands

```bash
# Fast local feedback
uv run pytest -q -m "not slow and not live"

# One product area
uv run pytest -q -m speech
uv run pytest -q -m conversation

# Deterministic full Python gate
uv run pytest

# Explicit real-model contract (requires configured credentials/model)
NOVA_AVATAR_LIVE_LLM_CONTRACT=1 uv run pytest -q -m live
```

The repository handoff gate remains:

```bash
uv run python scripts/check-integration.py
uv run pytest
cd web
npm test
npm run build
```

## Consolidation policy

Keep a separate module when it owns a distinct product contract or has a special
execution boundary. Merge very small modules into their owning suite when doing so
does not weaken the assertions or make the ownership ambiguous. Before deleting a
test, record which current test covers the same failure mode; if no replacement
exists, keep it.
