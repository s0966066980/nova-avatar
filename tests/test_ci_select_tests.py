# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""CI runs only the affected layers' tests; these cases pin that selection."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ci_select_tests", ROOT / "scripts/ci_select_tests.py")
ci_select = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ci_select)

SHARED = list(ci_select.SHARED_TESTS)
TESTPATHS = [*SHARED, *ci_select.LAYER_TESTS.values()]


def test_selectable_folders_are_exactly_pyprojects_testpaths(pytestconfig):
    """Plain ``pytest`` (the full run) and the union of the selections agree."""
    assert sorted(pytestconfig.getini("testpaths")) == sorted(TESTPATHS)


class SelectionTests(unittest.TestCase):

    def test_stt_only_change_skips_tts_llm_and_avatar_tests(self):
        selected = ci_select.select(["services/stt/nova_stt/factory.py"])
        self.assertEqual(selected, ["core/tests", "tests", "services/stt/tests"])

    def test_each_layer_selects_only_its_own_tests(self):
        for prefix, tests in ci_select.LAYER_TESTS.items():
            selected = ci_select.select([f"{prefix}pyproject.toml"])
            self.assertIn(tests, selected)
            others = set(ci_select.LAYER_TESTS.values()) - {tests}
            self.assertFalse(others & set(selected), prefix)

    def test_layer_selections_cover_every_test_folder_exactly_once(self):
        shared = ci_select.select(["docs/index.md"])
        self.assertEqual(shared, SHARED)
        union = list(shared)
        for prefix in ci_select.LAYER_TESTS:
            union += [p for p in ci_select.select([f"{prefix}x.py"]) if p not in shared]
        self.assertEqual(sorted(union), sorted(TESTPATHS))

    def test_changes_that_reach_every_layer_run_everything(self):
        for path in (
            "contracts/nova_contracts/stt.py",
            "core/nova_core/server/app.py",
            "core/tests/test_route_access.py",
            "pyproject.toml",
            "uv.lock",
            "conftest.py",
            ".github/workflows/ci.yml",
            "scripts/ci_select_tests.py",
            "config/config.yaml",
            "tests/test_dependency_lock.py",
            "somewhere/new/file.txt",
        ):
            self.assertIsNone(ci_select.select([path]), path)

    def test_one_global_path_among_layer_paths_runs_everything(self):
        self.assertIsNone(ci_select.select(["services/stt/nova_stt/factory.py", "uv.lock"]))

    def test_docs_and_frontend_only_changes_skip_layer_tests(self):
        for path in ("docs/adr/0021.md", "web/src/App.vue", "README.md", ".github/CODEOWNERS"):
            self.assertEqual(ci_select.select([path]), SHARED, path)

    def test_no_known_diff_runs_everything(self):
        self.assertIsNone(ci_select.select([]))
        self.assertIsNone(ci_select.changed_files("0" * 40))


if __name__ == "__main__":
    unittest.main()
