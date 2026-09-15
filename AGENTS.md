# Nova Avatar Agent Guide

Nova Avatar is an independently maintained derivative project originally based
on Kedreamix/Linly-Talker-Stream.

## Agent skills

### Issue tracker

Issues and specs are tracked as local Markdown under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

The default five-role triage vocabulary is used unchanged. See `docs/agents/triage-labels.md`.

### Domain docs

This repository uses a single-context domain-doc layout. See `docs/agents/domain.md`.

## Rebranding and source attribution

- Use `Nova Avatar` for user-visible branding, `nova-avatar` for package and
  repository slugs, and `HongXian0903` for project-maintainer attribution.
- Classify a change as project branding, inherited source, or third-party
  source before changing attribution.
- Inherited and modified files retain applicable upstream notices and include
  a prominent `Modified by HongXian0903, 2026` notice.
- Independently authored files use the Nova Avatar Apache-2.0 SPDX header.

## License guardrails

- Never remove or rebrand the root `LICENSE`.
- Never remove applicable upstream copyright or LiveTalking attribution.
- Keep MuseTalk's MIT license and Tencent Music Entertainment Group copyright.
- Never classify the bundled Wav2Lip integration as commercially permitted;
  label it `Research / Non-commercial` in user-visible surfaces.
- Do not assume that model, weight, dataset, voice, or service licenses match
  the root Apache-2.0 license.
- Consult `NOTICE` and `THIRD_PARTY_NOTICES.md` before changing third-party code.

## Validation

Run the relevant focused tests while editing, then complete the rebranding
audit and full validation before handoff:

```bash
uv run python scripts/check-integration.py
uv run pytest
cd web
npm test
npm run build
```
