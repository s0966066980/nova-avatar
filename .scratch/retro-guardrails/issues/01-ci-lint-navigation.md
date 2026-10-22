<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# Add CI, static checks, and graph navigation

Status: resolved

Implement the accepted [spec](../spec.md), validate the configured gates, and
record the final results below.

## Comments

- Initial Python baseline: 610 passed, 3 skipped.
- Ruff found an undefined `Path` in failed runtime-settings writes. A regression
  test reproduced the missing import, then passed after adding the import.
- A clean checkout exposed eager imports of optional MuseTalk model classes,
  undeclared test-environment extras, and an avatar-catalog assertion outside
  its temporary model fixture. Deferred model imports until loading, installed
  the declared `funasr`/`vad` extras in CI, and kept the assertion in its fixture.
  A regression test first reproduced the eager import, then passed after the fix.
- Delivered `.github/workflows/ci.yml`, Ruff and ESLint gates, and the
  [canonical graph-project pointer](../../../docs/agents/code-navigation.md).
- Final local Python 3.10 validation: **612 passed, 3 skipped**.
- Clean checkout and isolated Python 3.11 / PyTorch 2.5.0 CPU validation:
  **612 passed, 3 skipped**. Offline integration and Ruff also passed.
- Node.js 22: `npm ci`, frontend lint, **103 passing tests**, and production
  build passed. Existing frontend package versions were preserved.
- Representative Python, JavaScript, and Vue errors were rejected by the
  lint gates. Ruff's scope was verified across 173 maintained Python files.
- `actionlint` and `git diff --check` passed. Root `LICENSE`, `NOTICE`, and
  `THIRD_PARTY_NOTICES.md` were preserved; the modified MuseTalk utility retains
  MIT/Tencent attribution and the required modification notice.
- GitHub-hosted workflow execution will occur after these changes are pushed.
- npm reported 9 dependency audit findings; existing dependency upgrades are
  outside this change. The existing Vite chunk-size warning also remains.
