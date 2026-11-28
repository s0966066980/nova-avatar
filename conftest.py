# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Repository-wide pytest rules for Nova Avatar: the product-area check and the data/ guard."""

from __future__ import annotations

from pathlib import Path

import pytest


# Every test module names its product area itself, with ``pytestmark = pytest.mark.<area>``
# at module level (``live``, ``gpu`` and ``slow`` are marks on the module or the test in
# the same way). Nothing here lists test files: moving, adding or deleting a test never
# touches this file.
AREAS = ("avatar", "conversation", "governance", "llm", "ragflow", "runtime", "speech")


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    unclassified = {
        str(item.path.relative_to(Path(__file__).resolve().parent)).replace("\\", "/")
        for item in items
        if item.path.name.startswith("test_")
        and not any(item.get_closest_marker(area) for area in AREAS)
    }
    if unclassified:
        raise pytest.UsageError(
            "Test modules without a product area: " + ", ".join(sorted(unclassified))
            + ". Add `pytestmark = pytest.mark.<area>` (one of " + ", ".join(AREAS) + ")."
        )


# Tests write under tmp_path; the repository's data/ holds the venue's real
# avatars, voices and imports. A run that adds entries there fails.
REPO_DATA = Path(__file__).resolve().parent / "data"
_DATA_BEFORE = pytest.StashKey[frozenset]()


def repo_data_entries(root: Path = REPO_DATA) -> frozenset[str]:
    """``root`` itself plus its entries two levels deep (cheap even with real assets)."""
    if not root.is_dir():
        return frozenset()
    entries = {"."}
    for child in root.iterdir():
        entries.add(child.name)
        if child.is_dir() and not child.is_symlink():
            entries.update(f"{child.name}/{grandchild.name}" for grandchild in child.iterdir())
    return frozenset(entries)


def pytest_sessionstart(session: pytest.Session) -> None:
    session.config.stash[_DATA_BEFORE] = repo_data_entries()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    added = sorted(repo_data_entries() - session.config.stash[_DATA_BEFORE])
    if added:
        session.config.get_terminal_writer().line(
            f"\nTests wrote to the repository's data/ (use tmp_path): {', '.join(added)}", red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.fixture(autouse=True)
def _training_data_in_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    """A server started by a test must never recover or stop the venue's real training jobs.

    ``create_app`` builds the training manager on ``corpus.TRAINING_ROOT``, and the manager
    recovers (and may signal) the jobs saved under it at startup.
    """
    monkeypatch.setattr("nova_tts.training.corpus.TRAINING_ROOT", tmp_path_factory.mktemp("training-root"))
