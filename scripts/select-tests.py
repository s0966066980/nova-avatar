#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Choose which Python tests CI runs for a list of changed files (one per line on stdin).

Prints ``all``, ``none``, or space-separated pytest paths.

- Shared inputs (contracts, root manifests and lock, conftest, CI, scripts, the
  repo-level tests, the core) run everything: they can affect every layer.
- A processing layer runs its own tests plus ``core/tests`` (which exercise the
  layers together), never the other layers' tests.
- Docs and the web frontend run no Python tests (the web job covers the frontend).
"""
from __future__ import annotations

import sys

LAYERS = {
    "avatar/": "avatar/tests",
    "services/stt/": "services/stt/tests",
    "services/llm/": "services/llm/tests",
    "services/tts/": "services/tts/tests",
}
ALL_PREFIXES = ("contracts/", "core/", "tests/", "scripts/", ".github/", "third_party/", "config/")
ALL_FILES = {"pyproject.toml", "uv.lock", "conftest.py", "NOTICE", "THIRD_PARTY_NOTICES.md", "LICENSE"}
IGNORED_PREFIXES = ("docs/", "web/", ".scratch/", "assets/")
IGNORED_SUFFIXES = (".md",)


def select(changed: list[str]) -> list[str] | None:
    """Pytest paths for ``changed``; ``None`` means run everything, ``[]`` nothing."""
    paths: set[str] = set()
    for name in changed:
        name = name.strip()
        if not name:
            continue
        if name in ALL_FILES or (name.startswith(ALL_PREFIXES) and not name.endswith(IGNORED_SUFFIXES)):
            return None
        if name.endswith(IGNORED_SUFFIXES) and name not in ALL_FILES:
            continue
        layer = next((tests for prefix, tests in LAYERS.items() if name.startswith(prefix)), None)
        if layer:
            paths.update({layer, "core/tests"})
        elif not name.startswith(IGNORED_PREFIXES) and not name.endswith(IGNORED_SUFFIXES):
            return None  # unknown location: be safe
    return sorted(paths)


def main() -> int:
    chosen = select(sys.stdin.read().splitlines())
    print("all" if chosen is None else " ".join(chosen) if chosen else "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
