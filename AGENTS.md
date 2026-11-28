# Nova Avatar Agent Guide

Nova Avatar is an independently maintained derivative project originally based
on Kedreamix/Linly-Talker-Stream.

## Language

Reply to the user in Traditional Chinese (繁體中文), including progress updates.
Code, identifiers, commands, and file paths stay in their original language.

Written artifacts follow the existing convention of this repository:

- Commit messages and code comments: English (Conventional Commits prefixes
  such as `feat:`, `fix:`, `docs:`).
- `README.md`, `docs/` (including ADRs), and local `.scratch/` issues and specs:
  Traditional Chinese. Keep the English headings of `docs/agents/*`.
- User-visible UI text: Traditional Chinese.

## Agent skills

### Code navigation

For this repository, use codebase-memory-mcp with `project="nova-avatar"`.
See `docs/agents/code-navigation.md` when selecting or refreshing its index.

### Issue tracker

Issues and specs are local Markdown under `.scratch/`, which is git-ignored and never pushed. See `docs/agents/issue-tracker.md`.

### Triage labels

The default five-role triage vocabulary is used unchanged. See `docs/agents/triage-labels.md`.

### Domain docs

This repository uses a single-context domain-doc layout. See `docs/agents/domain.md`.

## Repository layout

Code is split by processing layer (ADR 0027, ADR 0028); there is no `src/`
directory. Every folder below has its own `pyproject.toml`, `tests/` and
`README.md`, which state its responsibility, public interface, engines and how
to test it.

| Folder | Python package | Holds |
|---|---|---|
| `contracts/` | `nova_contracts` | Cross-layer Pydantic models and Protocols |
| `core/` | `nova_core` | Server, turn orchestration, VAD, profiles, config, greetings, shared `utils` |
| `services/stt/` | `nova_stt` | Speech-to-text |
| `services/llm/` | `nova_llm` | LLM, handoff, weather, AI greetings, `ragflow`, `web_search` |
| `services/tts/` | `nova_tts` | TTS engines, voice library, voice models, voice training |
| `avatar/` | `nova_render` | Avatar rendering (MuseTalk) and stage `scene` |

- Layer-specific setup and weight scripts live in `<layer>/scripts/`; `scripts/`
  holds the cross-layer ones.
- Tests that need the core (config, server, several layers) live in `core/tests/`;
  `tests/` keeps repository-wide ones. See `tests/README.md`.
- `lint-imports` enforces the layer boundaries; a layer is reached from the core
  only through its `adapter` and `config_section` modules.
- `docs/` holds maintained documents only: `guides/` (install and operation),
  `project/` (status, workflow, test baseline, software stack, attribution audit),
  `adr/` and `agents/`; start from `docs/README.md`.
- `integrations/` holds deployment files for external services and separate
  environments (`ragflow/`, `matcha-train/` with its requirements and training
  scripts).
- `.scratch/` is local only and git-ignored; never commit or link to it.

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

## Trust boundary

Before adding or changing a route, read `docs/adr/0021-stage-local-console-login.md`:
every route is public, stage (loopback only), or admin (login required).

## Review

When reviewing a change, apply every rule in `CODING_STANDARDS.md`.

## Validation

Before handoff, run every step in `.github/workflows/ci.yml`; its
`scripts/check-integration.py` step is the rebranding audit.

- Run Python steps through `uv run --no-sync`, as CI does. The system Python
  lacks the project dependencies (for example `opencc`).
- For a documentation-only change, running `scripts/check-integration.py` is
  enough; the full test suite and web build can be skipped.
