<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# Current Project Workflow

Updated: 2026-09-15

This document replaces informal carry-over work with a repeatable Nova Avatar
maintenance flow. The current baseline is documented in
[project-status.md](project-status.md); active specifications and work items
belong in `.scratch/` under the repository's issue-tracker convention.

## Start a new work item

1. Check `docs/project-status.md`, `CONTEXT.md`, relevant ADRs, and the
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
   environment with `uv sync --group dev`.
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

## Release handoff

1. Run branding and third-party audits; retained upstream names must be
   attributable, not user-facing product branding.
2. Confirm the distribution's selected configuration and external artifacts
   against `THIRD_PARTY_NOTICES.md` and `docs/software-stack.md`.
3. Keep the root `LICENSE` unchanged, retain applicable notices, and classify
   every changed source file before altering its attribution header.
4. Link the final verification results from the active `.scratch/` work item
   and update the project status only after the gates pass.
