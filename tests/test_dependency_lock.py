# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""CI tests the dependency versions pinned in the tracked uv.lock."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "uv.lock"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
UV = shutil.which("uv")


def _steps(job: str) -> list[dict]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"][job]["steps"]


def _step_index(steps: list[dict], command: str) -> int:
    for index, step in enumerate(steps):
        if command in step.get("run", ""):
            return index
    raise AssertionError(f"no CI step runs {command!r}")


def _lock_check(project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [UV, "lock", "--check", "--offline", "--directory", str(project)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


class DependencyLockTests(unittest.TestCase):
    def test_lock_is_present_and_not_ignored_by_git(self):
        self.assertTrue(LOCK.is_file(), "uv.lock must be committed")
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertNotIn("uv.lock", [line.strip() for line in gitignore])

    def test_python_ci_checks_the_lock_before_installing(self):
        steps = _steps("python")
        lock_check = _step_index(steps, "uv lock --check")
        install = _step_index(steps, "uv pip install")
        self.assertLess(lock_check, install)
        self.assertNotIn("continue-on-error", steps[lock_check])
        # The CPU-only PyTorch install path is unchanged.
        self.assertIn("--torch-backend cpu", steps[install]["run"])

    def test_web_ci_audits_production_dependencies_without_blocking(self):
        steps = _steps("web")
        audit = steps[_step_index(steps, "npm audit --omit=dev")]
        self.assertIs(audit.get("continue-on-error"), True)


@unittest.skipIf(UV is None, "uv is not installed")
class LockCheckTests(unittest.TestCase):
    def _project_copy(self, tmp: Path) -> Path:
        """Copy only the lock inputs: both project manifests and the lock."""
        for manifest in ("pyproject.toml", "src/avatars/musetalk/pyproject.toml"):
            target = tmp / manifest
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / manifest, target)
        shutil.copy2(LOCK, tmp / "uv.lock")
        return tmp

    def test_lock_matches_pyproject(self):
        result = _lock_check(ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_dependency_change_without_lock_update_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project_copy(Path(tmp))
            control = _lock_check(project)
            self.assertEqual(control.returncode, 0, control.stderr)
            pyproject = project / "pyproject.toml"
            text = pyproject.read_text(encoding="utf-8")
            self.assertIn('    "PyYAML",\n', text)
            pyproject.write_text(text.replace('    "PyYAML",\n', "", 1), encoding="utf-8")
            result = _lock_check(project)
        # Offline with a cold cache uv cannot re-resolve and reports that instead
        # of a stale lock; either way the unchanged control passed and this fails.
        self.assertNotEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
