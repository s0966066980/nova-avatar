<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# Current Project Workflow

Updated: 2026-10-22

This document replaces informal carry-over work with a repeatable Nova Avatar
maintenance flow. The current baseline is documented in
[project-status.md](project-status.md); active specifications and work items
belong in `.scratch/` under the repository's issue-tracker convention.

## Start a new work item

1. Check `docs/project-status.md`, `CONTEXT.md`, relevant ADRs in `docs/adr/`, and the
   [source attribution audit](source-attribution-audit.md).
2. Create `.scratch/<feature>/spec.md` and one issue file per implementation
   concern under `.scratch/<feature>/issues/`.
3. Use the labels from `docs/agents/triage-labels.md`; do not treat old
   benchmark files as open work by themselves.
4. Choose the relevant configuration and document whether the work affects the
   commercial review profile or a restricted third-party component.

## Implement and validate

1. Make the smallest source, configuration, and documentation change that
   satisfies the accepted work item.
2. Run focused tests first. For validation commands, prepare the development
   environment with `uv sync --group dev`, then run `uv run ruff check .`,
   `uv run pyright`, and `npm --prefix web run lint`. Ruff covers application
   code, scripts, and tests; bundled engine/vendor directories are excluded in
   `pyproject.toml`. Pyright checks `src/server` for unbound and possibly
   unbound names plus the basic-mode rules that currently pass there. ESLint
   covers frontend source, tests, and configuration with JavaScript recommended
   and Vue essential rules. The initial gate defers unused-code cleanup and
   error-cause conventions, as documented in `web/eslint.config.js`.
3. Run the offline project check:

   ```bash
   uv run python scripts/check-integration.py
   ```

4. Only when the configured LLM and TTS services are intentionally available,
   run their smoke check; it writes no audio unless an output path is supplied:

   ```bash
   uv run python scripts/check-integration.py --smoke
   ```

5. Before handoff, run Python tests, frontend tests, and the production build.
   Run a voice/WebRTC soak only when its real services and hardware are in
   scope; record the report path in the active work item's comments.

GitHub Actions runs these offline checks on pushes and pull requests through
`.github/workflows/ci.yml`. Its Python job uses Python 3.11, CPU PyTorch wheels,
the `funasr` and `vad` extras, and the `dev` and `ci` dependency groups. The `ci`
group supplies the MuseTalk import probes required by the offline check without
loading models. To reproduce the Python job in a separate environment:

```bash
export UV_PROJECT_ENVIRONMENT=/tmp/nova-avatar-ci-venv
uv venv --python 3.11 "$UV_PROJECT_ENVIRONMENT"
uv pip install --python "$UV_PROJECT_ENVIRONMENT/bin/python" \
  --no-sources --torch-backend cpu --group dev --group ci -e '.[funasr,vad]'
uv run --no-sync ruff check .
uv run --no-sync pyright
uv run --no-sync python scripts/check-integration.py
uv run --no-sync pytest
```

Keep `--no-sync` for commands in that isolated environment so they retain the
installed CPU wheels instead of resolving the deployment's CUDA index again.
The CPU backend uses uv's [PyTorch pip integration](https://docs.astral.sh/uv/guides/integration/pytorch/#automatic-backend-selection).

The frontend job uses Node.js 22 and runs `npm ci`, `npm run lint`, `npm test`,
and `npm run build` inside `web/`. Live service and hardware checks remain
explicitly invoked checks outside this offline workflow.

## 清除過往工作項目與流程

1. Treat `.scratch/` specifications, issue files, prototypes, screenshots, and
   soak JSON files as evidence, not as implicit backlog.
2. For every previous work item, record its final state in its issue/spec:
   delivered, superseded, blocked, or retained as a benchmark. Preserve the
   evidence and link it from the current work item when it still supports a
   release claim.
3. Move obsolete experimental artifacts out of the active feature directory
   only after a maintainer confirms their exact paths and retention need. Do
   not delete a broad `.scratch/` directory as cleanup.
4. Update `docs/project-status.md` only with completed, reproducibly verified
   capabilities. Do not promote a local prototype or an unrerun benchmark to
   the current baseline.
5. When a work item is superseded, add a short pointer to its replacement;
   do not erase its licensing, benchmark, or decision history.
6. Keep `docs/` limited to maintained references: the project status, this
   workflow, the software stack, the source attribution audit, component
   guides such as `ragflow.md`, and ADRs. One-off implementation prompts and
   task specifications belong in `.scratch/`; once delivered, record any
   lasting decision as an ADR and remove the prompt instead of keeping a
   stale copy in `docs/`.

## Release handoff

1. Run branding and third-party audits; retained upstream names must be
   attributable, not user-facing product branding.
2. Confirm the distribution's selected configuration and external artifacts
   against `THIRD_PARTY_NOTICES.md` and `docs/software-stack.md`.
3. Keep the root `LICENSE` unchanged, retain applicable notices, and classify
   every changed source file before altering its attribution header.
4. Link the final verification results from the active `.scratch/` work item
   and update the project status only after the gates pass.

### Branding and third-party audit

```bash
git grep -n -I -E 'Linly-Talker-Stream|Linly_Talker_Stream|linly-talker|Kedreamix|kedreamix'
git grep -n -I -E 'Wav2Lip|MuseTalk|LiveTalking|Whisper|FunASR|TalkingGaussian|ER-NeRF'
```

Upstream names are expected in `NOTICE`, `THIRD_PARTY_NOTICES.md`, README
references, and inherited-source attribution. Only current UI titles, package
metadata, product descriptions, and user-facing prompts must use Nova Avatar.
Third-party engine names are not expected to reach zero matches.

### Release checklist

- Legal: `LICENSE` and `NOTICE` exist; Kedreamix, LiveTalking (where
  applicable), and MuseTalk MIT attribution are retained; modified inherited
  sources carry a change notice; Wav2Lip is marked
  **Research / Non-commercial**; no third-party model is described as
  Apache-2.0.
- Branding: user-visible product name is Nova Avatar; package slugs are
  `nova-avatar` and `nova-avatar-web`; the repository URL is correct; old
  branding does not appear in the current UI.
- Runtime: backend start, frontend build, WebRTC connection, microphone, VAD,
  STT, LLM, TTS, MuseTalk, interruption, playback commit, caption lifecycle,
  and runtime settings are exercised on the selected distribution
  configuration.
