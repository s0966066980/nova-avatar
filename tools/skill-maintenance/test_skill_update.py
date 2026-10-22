# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Exercise updates and recovery against isolated local Git repositories."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import skill_update as update


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.state.mkdir()
        self.cache_root = self.root / "cache"
        self.repo = self.root / "upstream"
        self.repo.mkdir()
        self.source = "example/skills"
        self.specs = {
            "alpha": {"path": "skills/alpha", "upstream_name": "alpha"},
            "local-research": {"path": "skills/research", "upstream_name": "research"},
        }
        update.git(self.repo, "init", "--quiet", "--initial-branch=main")
        update.git(self.repo, "config", "user.name", "Skill updater tests")
        update.git(self.repo, "config", "user.email", "skills@example.invalid")
        for spec in self.specs.values():
            directory = self.repo / spec["path"]
            directory.mkdir(parents=True)
            (directory / "SKILL.md").write_text(
                f"---\nname: {spec['upstream_name']}\ndescription: Test skill\n---\nOriginal body.\n"
            )
        (self.repo / "skills/alpha/old.txt").write_text("obsolete")
        self.commit = self.commit_changes("initial")
        self.external = self.root / "external-lock.json"
        tree = update.git(self.repo, "rev-parse", "HEAD:skills/alpha").decode().strip()
        self.external.write_bytes(update.json_bytes({"version": 3, "skills": {
            "alpha": {"source": self.source, "skillPath": "skills/alpha/SKILL.md", "skillFolderHash": tree},
            "research": {"source": "someone/other-skills", "kept": True},
        }}))
        assets = update.upstream_assets(self.repo, self.commit, self.specs)
        for name, files in assets.items():
            for rel, asset in files.items():
                path = self.state / "skills" / name / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(asset.data)
                path.chmod(asset.mode)
            self.specs[name]["files"] = update.fingerprints(files)
        registry = {"version": 1, "skills_directory": str(self.state / "skills"),
                    "external_lock": str(self.external), "sources": {self.source: {
                        "url": str(self.repo), "default_ref": "main", "commit": self.commit,
                        "skills": self.specs}}}
        self.manager = update.Maintenance(self.state)
        self.manager.registry_path.write_bytes(update.json_bytes(registry))
        update.fetch_commit(self.cache_root, self.source, str(self.repo), "main", False)

    def commit_changes(self, message):
        update.git(self.repo, "add", ".")
        update.git(self.repo, "commit", "--quiet", "-m", message)
        return update.git(self.repo, "rev-parse", "HEAD").decode().strip()

    def change_upstream(self):
        (self.repo / "skills/alpha/old.txt").unlink()
        (self.repo / "skills/alpha/new.txt").write_text("new content")
        manifest = self.repo / "skills/research/SKILL.md"
        manifest.write_text(manifest.read_text().replace("Original body.", "Updated body."))
        return self.commit_changes("update skills")

    def snapshot(self):
        return self.manager.snapshot(self.source)[0]

    def run_update(self, apply=False, offline=False):
        return self.manager.update(self.source, self.cache_root, None, offline, apply)

    def assert_snapshot_equal(self, left, right):
        self.assertEqual(update.snapshot_fingerprint(left), update.snapshot_fingerprint(right))

    def test_check_covers_aliased_skill_missing_from_external_lock(self):
        result = self.manager.check(self.source)
        self.assertEqual((result["skills"], result["conflicts"]), (2, 0))

    def test_preview_fetches_once_and_changes_no_installed_state(self):
        self.change_upstream()
        before = self.snapshot()
        original = update.git
        calls = []

        def record(directory, *arguments):
            if arguments[0] == "fetch":
                calls.append(arguments)
            return original(directory, *arguments)

        with patch.object(update, "git", record):
            result = self.run_update()
        self.assertEqual(result["status"], "preview")
        self.assertEqual(result["changed"], 2)
        self.assertEqual(len(calls), 1)
        self.assert_snapshot_equal(before, self.snapshot())
        self.assertFalse((self.state / "skill-backups").exists())

    def test_apply_preserves_alias_and_unrelated_lock_record(self):
        commit = self.change_upstream()
        unrelated = json.loads(self.external.read_bytes())["skills"]["research"]
        result = self.run_update(apply=True)
        self.assertEqual(result["status"], "updated")
        self.assertEqual(result["commit"], commit)
        self.assertFalse((self.state / "skills/alpha/old.txt").exists())
        self.assertEqual((self.state / "skills/alpha/new.txt").read_text(), "new content")
        text = (self.state / "skills/local-research/SKILL.md").read_text()
        self.assertIn("name: local-research\n", text)
        self.assertIn("Updated body.", text)
        self.assertEqual(json.loads(self.external.read_bytes())["skills"]["research"], unrelated)
        self.assertEqual(self.manager.check(self.source)["conflicts"], 0)

    def test_second_apply_is_a_no_op(self):
        self.change_upstream()
        self.run_update(apply=True)
        before = self.snapshot()
        backups = list((self.state / "skill-backups").iterdir())
        result = self.run_update(apply=True, offline=True)
        self.assertEqual(result["status"], "current")
        self.assert_snapshot_equal(before, self.snapshot())
        self.assertEqual(list((self.state / "skill-backups").iterdir()), backups)

    def test_local_modification_blocks_update_before_fetch(self):
        manifest = self.state / "skills/alpha/SKILL.md"
        manifest.write_text(manifest.read_text() + "My custom edit.\n")
        before = self.snapshot()
        with patch.object(update, "fetch_commit", side_effect=AssertionError("must not fetch")):
            result = self.run_update(apply=True)
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["conflicts"], 1)
        self.assert_snapshot_equal(before, self.snapshot())

    def test_unregistered_lock_entry_is_a_coverage_error(self):
        lock = json.loads(self.external.read_bytes())
        lock["skills"]["forgotten"] = {"source": self.source}
        self.external.write_bytes(update.json_bytes(lock))
        self.assertEqual(self.manager.check(self.source)["conflicts"], 1)

    def test_local_extra_file_is_a_conflict(self):
        (self.state / "skills/alpha/custom.txt").write_text("keep")
        self.assertEqual(self.manager.check(self.source)["conflicts"], 1)

    def test_local_permission_edit_is_a_conflict(self):
        (self.state / "skills/alpha/SKILL.md").chmod(0o755)
        self.assertEqual(self.manager.check(self.source)["conflicts"], 1)

    def test_failed_write_restores_files_registry_and_external_lock(self):
        self.change_upstream()
        before = self.snapshot()
        original = update.atomic_write
        failed = False

        def fail_once(path, data, mode=0o600):
            nonlocal failed
            if path == self.manager.registry_path and not failed:
                failed = True
                raise OSError("simulated disk error")
            return original(path, data, mode)

        with patch.object(update, "atomic_write", fail_once):
            with self.assertRaisesRegex(update.MaintenanceError, "was rolled back"):
                self.run_update(apply=True)
        self.assert_snapshot_equal(before, self.snapshot())
        manifest = next((self.state / "skill-backups").glob("*/manifest.json"))
        self.assertEqual(json.loads(manifest.read_bytes())["status"], "rolled-back")

    def test_restore_preview_then_restore_and_redo(self):
        before = self.snapshot()
        self.change_upstream()
        installed = self.run_update(apply=True)
        after = self.snapshot()
        preview = self.manager.restore(Path(installed["backup"]), False)
        self.assertEqual(preview["status"], "restore-preview")
        self.assert_snapshot_equal(after, self.snapshot())
        restored = self.manager.restore(Path(installed["backup"]), True)
        self.assert_snapshot_equal(before, self.snapshot())
        self.manager.restore(Path(restored["backup"]), True)
        self.assert_snapshot_equal(after, self.snapshot())

    def test_restore_refuses_new_edits(self):
        self.change_upstream()
        result = self.run_update(apply=True)
        (self.state / "skills/alpha/new.txt").write_text("edited after update")
        with self.assertRaisesRegex(update.MaintenanceError, "changed since this backup"):
            self.manager.restore(Path(result["backup"]), True)

    def test_restore_refuses_corrupt_backup(self):
        self.change_upstream()
        result = self.run_update(apply=True)
        backup = Path(result["backup"])
        (backup / "skills/alpha/old.txt").write_text("corrupted")
        with self.assertRaisesRegex(update.MaintenanceError, "checksum"):
            self.manager.restore(backup, True)

    def test_recover_interrupted_update_with_partial_files(self):
        before = self.snapshot()
        self.change_upstream()
        result = self.run_update(apply=True)
        backup = Path(result["backup"])
        manifest = json.loads((backup / "manifest.json").read_bytes())
        manifest["status"] = "applying"
        (backup / "manifest.json").write_bytes(update.json_bytes(manifest))
        old = before.skills["local-research"]["SKILL.md"]
        update.atomic_write(self.state / "skills/local-research/SKILL.md", old.data, old.mode)
        self.manager.restore(backup, True)
        self.assert_snapshot_equal(before, self.snapshot())

    def test_missing_offline_cache_is_an_error(self):
        with self.assertRaisesRegex(update.MaintenanceError, "No cached"):
            update.fetch_commit(self.root / "empty-cache", self.source, str(self.repo), "main", True)

    def test_executable_bits_are_preserved(self):
        script = self.repo / "skills/alpha/run.sh"
        script.write_text("#!/bin/sh\nexit 0\n")
        script.chmod(0o755)
        self.commit_changes("add executable")
        self.run_update(apply=True)
        self.assertEqual((self.state / "skills/alpha/run.sh").stat().st_mode & 0o777, 0o755)

    def test_registered_read_write_permissions_are_preserved(self):
        manifest = self.state / "skills/alpha/SKILL.md"
        manifest.chmod(0o664)
        registry = json.loads(self.manager.registry_path.read_bytes())
        registry["sources"][self.source]["skills"]["alpha"]["files"] = update.fingerprints(
            update.read_assets(self.state / "skills/alpha"))
        self.manager.registry_path.write_bytes(update.json_bytes(registry))
        self.change_upstream()
        self.run_update(apply=True)
        self.assertEqual(manifest.stat().st_mode & 0o777, 0o664)

    def test_upstream_symlink_is_rejected(self):
        (self.repo / "skills/alpha/link").symlink_to("SKILL.md")
        self.commit_changes("symlink")
        with self.assertRaisesRegex(update.MaintenanceError, "file type"):
            self.run_update(apply=True)

    def test_local_symlink_is_rejected(self):
        (self.state / "skills/alpha/link").symlink_to("SKILL.md")
        with self.assertRaisesRegex(update.MaintenanceError, "symlink"):
            self.manager.check(self.source)

    def test_registry_path_traversal_is_rejected(self):
        registry = json.loads(self.manager.registry_path.read_bytes())
        spec = registry["sources"][self.source]["skills"].pop("alpha")
        registry["sources"][self.source]["skills"]["../escape"] = spec
        self.manager.registry_path.write_bytes(update.json_bytes(registry))
        with self.assertRaisesRegex(update.MaintenanceError, "Unsafe relative"):
            self.manager.check(self.source)

    def test_update_detects_changes_during_preparation(self):
        before = self.snapshot()
        (self.state / "skills/alpha/old.txt").write_text("concurrent edit")
        with self.assertRaisesRegex(update.MaintenanceError, "changed during preparation"):
            self.manager.transact(self.source, before, before)

    def test_change_during_backup_is_preserved(self):
        self.change_upstream()
        original = update.atomic_write
        edited = self.state / "skills/alpha/old.txt"
        injected = False

        def edit_during_backup(path, data, mode=0o600):
            nonlocal injected
            result = original(path, data, mode)
            if path.name == "manifest.json" and not injected:
                injected = True
                edited.write_text("external edit while backing up")
            return result

        with patch.object(update, "atomic_write", edit_during_backup):
            with self.assertRaisesRegex(update.MaintenanceError, "while creating the backup"):
                self.run_update(apply=True)
        self.assertEqual(edited.read_text(), "external edit while backing up")

    def test_file_to_directory_transition_and_restore(self):
        before = self.snapshot()
        path = self.repo / "skills/alpha/old.txt"
        path.unlink()
        path.mkdir()
        (path / "child.txt").write_text("child")
        self.commit_changes("file becomes directory")
        result = self.run_update(apply=True)
        self.assertTrue((self.state / "skills/alpha/old.txt/child.txt").is_file())
        self.manager.restore(Path(result["backup"]), True)
        self.assert_snapshot_equal(before, self.snapshot())

    def test_unexpected_upstream_name_is_rejected(self):
        manifest = self.repo / "skills/research/SKILL.md"
        manifest.write_text(manifest.read_text().replace("name: research", "name: other"))
        self.commit_changes("unexpected rename")
        with self.assertRaisesRegex(update.MaintenanceError, "Unexpected upstream manifest name"):
            self.run_update(apply=True)

    def test_exclusive_lock_blocks_another_command(self):
        with self.manager.exclusive():
            with self.assertRaisesRegex(update.MaintenanceError, "Another skill"):
                with update.Maintenance(self.state).exclusive():
                    pass

    def test_cli_output_is_compact(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = update.main(["--state-dir", str(self.state), "check", self.source])
        self.assertEqual(code, 0)
        self.assertLessEqual(len(output.getvalue().splitlines()), 4)
        self.assertLess(len(output.getvalue()), 1000)

    def test_json_output_is_summary_only(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = update.main(["--state-dir", str(self.state), "--json", "check", self.source])
        self.assertEqual(code, 0)
        summary = json.loads(output.getvalue())
        self.assertEqual(summary["skills"], 2)
        self.assertNotIn("details", summary)
        self.assertLess(len(output.getvalue()), 1000)

    def test_failure_is_logged_and_returns_nonzero(self):
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            code = update.main(["--state-dir", str(self.state), "check", "missing/source"])
        self.assertEqual(code, 1)
        self.assertIn("Report:", error.getvalue())

    def test_metadata_only_commit_is_recoverable(self):
        before = self.snapshot()
        (self.repo / "README.md").write_text("Only upstream docs changed")
        self.commit_changes("documentation")
        result = self.run_update(apply=True)
        self.assertEqual((result["status"], result["changed"]), ("updated", 0))
        self.manager.restore(Path(result["backup"]), True)
        self.assert_snapshot_equal(before, self.snapshot())


if __name__ == "__main__":
    unittest.main()
