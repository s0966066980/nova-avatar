# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Choose the pytest folders CI runs for a set of changed files.

Every processing layer owns a ``tests/`` folder; ``core/tests`` and the root
``tests/`` are shared and always run. A layer's own tests run when files inside
that layer changed or when a change can reach every layer. The result is printed
as GitHub step output: ``pytest_args`` is empty for "run everything" (plain
``pytest`` then collects ``testpaths`` unchanged).

Any doubt selects everything: no diff, a failed ``git diff`` and any path this
script does not know all run the full suite.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Run for every change, in the order pyproject.toml lists them under testpaths
# (tests/test_ci_select_tests.py fails when the two drift apart).
SHARED_TESTS = ("core/tests", "tests")

# Layer source folder -> the folder holding that layer's own tests.
LAYER_TESTS = {
    "avatar/": "avatar/tests",
    "services/stt/": "services/stt/tests",
    "services/llm/": "services/llm/tests",
    "services/tts/": "services/tts/tests",
}

# Paths no layer test reads. The shared suites (core/tests, tests/) still run for
# them, so a documentation or branding change is checked by the audits.
INERT_PREFIXES = ("docs/", "web/", ".scratch/")
INERT_FILES = frozenset({".github/CODEOWNERS", "LICENSE", "NOTICE"})


def _is_inert(path: str) -> bool:
    return (
        path in INERT_FILES
        or path.startswith(INERT_PREFIXES)
        or ("/" not in path and path.endswith(".md"))
    )


def select(changed: list[str]) -> list[str] | None:
    """Return the test folders to run, or ``None`` for the full suite.

    Everything not under a layer folder and not inert implies the full suite:
    ``contracts/``, ``core/`` (every layer's tests share its fixtures and the
    root ``conftest.py``), the root ``pyproject.toml``, ``uv.lock`` and this
    workflow, but also configuration and scripts nobody classified yet.
    """
    if not changed:
        return None
    layers: set[str] = set()
    for path in changed:
        for prefix, tests in LAYER_TESTS.items():
            if path.startswith(prefix):
                layers.add(tests)
                break
        else:
            if not _is_inert(path):
                return None
    return [*SHARED_TESTS, *(t for t in LAYER_TESTS.values() if t in layers)]


def changed_files(base: str) -> list[str] | None:
    """Files changed between ``base`` and HEAD, or ``None`` when git cannot say."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--no-renames", base, "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return [line for line in result.stdout.splitlines() if line]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="git ref to diff HEAD against; omit to run everything")
    args = parser.parse_args(argv)

    changed = changed_files(args.base) if args.base else None
    selected = select(changed) if changed else None
    if selected is None:
        print("pytest scope: everything", file=sys.stderr)
        print("pytest_args=")
    else:
        print(f"pytest scope: {' '.join(selected)}", file=sys.stderr)
        print(f"pytest_args={' '.join(selected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
