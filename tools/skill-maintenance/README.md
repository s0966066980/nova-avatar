<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# Local skill maintenance

Use `skill-update` to maintain already installed skills from a registered source.
The command uses Python 3 and Git, with no Python package dependencies.

This directory is the maintained Nova Avatar source for the user-level tool.
Run it directly with `python3 tools/skill-maintenance/skill_update.py`, or copy
`skill_update.py`, `README.md`, `check` and `test_skill_update.py` into
`~/.codex/tools/skill-maintenance/` and link `skill_update.py` from
`~/.local/bin/skill-update`.

The [registry example](examples/skill-sources.json) contains the 37 registered
upstream paths, aliases and verified snapshot fingerprints. Its two absolute
path placeholders must be replaced before using it as
`~/.codex/skill-sources.json`. Keep an existing runtime registry when updating
the tool. On another installation, verify the installed files against the
recorded upstream commit before establishing its baseline; `check` reports
content or permission differences rather than adopting them silently.

```sh
skill-update check mattpocock/skills
skill-update update mattpocock/skills
skill-update update mattpocock/skills --apply
```

`check` verifies the local files and source coverage without using the network.
`update` previews changes by default. It fetches the requested Git ref once into
a persistent cache and reads every skill from that same commit. For a reviewed
commit, pass `--ref COMMIT` when applying. `--offline` uses the cached ref and
does not establish whether it is still the latest upstream version.

Default output is a short summary and report path. Start with that summary;
open the report only to inspect changed paths or resolve a conflict. The global
`--json` option prints the same summary as one JSON object. Detailed reports stay
under `~/.codex/skill-maintenance/reports/`.

## Source records and local edits

`~/.codex/skill-sources.json` records each source, upstream skill path, local name,
commit and installed file fingerprints. It currently covers all 37 installed
skills from `mattpocock/skills`, including the alias `research` →
`mattpocock-research`. That alias keeps the separate installed `research` skill
from another source intact.

The updater operates on registered skills only. It preserves aliases and local
read/write permissions while following upstream executable bits. It updates
matching entries already present in `~/.agents/.skill-lock.json`, leaving other
entries intact. The dedicated registry also covers skills absent from that lock.

Local content, permission or extra-file changes stop an update before fetching.
Inspect the reported paths and reconcile intentional edits with upstream before
updating. Symlinks and unsafe paths are rejected. Commands use an exclusive lock
and verify the installation again before writing.

## Recovery

Applying creates a backup of all registered skills for that source, the source
registry and the external lock. A failed write triggers automatic rollback.
Successful updates print the backup path.

```sh
skill-update restore /absolute/path/to/managed-backup
skill-update restore /absolute/path/to/managed-backup --apply
```

Restoring defaults to preview. It verifies backup checksums and refuses to
overwrite edits made after the update. An interrupted update can be recovered
when its files still match either the saved originals or planned replacements.
Applying a restore creates another backup, so the restoration itself can be undone.

Earlier manual backup archives remain audit copies. `restore` accepts this
tool's `managed-*` backup format only.

## Validation

Run the local check command after changing this tool:

```sh
~/.codex/tools/skill-maintenance/check
```

It runs isolated local Git integration tests, then checks the real registered
installation when a runtime registry exists. Tests cover preview, alias preservation, drift, executable bits,
one-fetch behavior, rollback, interrupted recovery, restore conflicts and compact
output. `--state-dir` and `--cache-dir` isolate other environments and tests.
