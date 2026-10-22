#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Maintain registered skills with compact reports and recoverable updates."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import tempfile
import uuid


class MaintenanceError(Exception):
    pass


@dataclass(frozen=True)
class Asset:
    data: bytes
    mode: int = 0o644


@dataclass
class Snapshot:
    registry: bytes
    external_lock: bytes | None
    skills: dict[str, dict[str, Asset]]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(p in ("", ".", "..") for p in value.split("/")):
        raise MaintenanceError(f"Unsafe relative path: {value!r}")
    return value


def local_name(value: str) -> str:
    safe_relative(value)
    if "/" in value or value.startswith(".") or "\\" in value:
        raise MaintenanceError(f"Invalid skill name: {value!r}")
    return value


def normalize_source(value: str) -> str:
    value = value.removeprefix("https://github.com/").rstrip("/").removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise MaintenanceError("Source must be owner/repo or a GitHub repository URL")
    return value


def read_assets(root: Path) -> dict[str, Asset]:
    if root.is_symlink() or not root.is_dir():
        raise MaintenanceError(f"Skill directory is missing or is a symlink: {root}")
    assets = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise MaintenanceError(f"Resolve this symlink before updating: {path}")
        if path.is_file():
            rel = safe_relative(path.relative_to(root).as_posix())
            assets[rel] = Asset(path.read_bytes(), path.stat().st_mode & 0o777)
        elif not path.is_dir():
            raise MaintenanceError(f"Unsupported file type: {path}")
    return assets


def fingerprints(assets: dict[str, Asset]) -> dict:
    return {name: {"sha256": digest(a.data), "mode": a.mode} for name, a in assets.items()}


def snapshot_fingerprint(snapshot: Snapshot) -> dict:
    return {
        "registry": digest(snapshot.registry),
        "external_lock": None if snapshot.external_lock is None else digest(snapshot.external_lock),
        "skills": {name: fingerprints(assets) for name, assets in snapshot.skills.items()},
    }


def changed_files(before: dict[str, Asset], after: dict[str, Asset]) -> list[str]:
    return sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))


def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".skill-update-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def git(directory: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), *arguments], capture_output=True,
            stdin=subprocess.DEVNULL, timeout=120,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MaintenanceError(f"Git failed: {exc}") from exc
    if result.returncode:
        raise MaintenanceError(result.stderr.decode(errors="replace").strip()[:1500] or "Git failed")
    return result.stdout


def cache_path(cache_root: Path, source: str) -> Path:
    return cache_root / (source.replace("/", "--") + ".git")


def cache_ref(ref: str) -> str:
    return "refs/skill-maintenance/" + digest(ref.encode())


def fetch_commit(cache_root: Path, source: str, url: str, ref: str, offline: bool) -> tuple[Path, str]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", ref) or ".." in ref:
        raise MaintenanceError(f"Invalid Git ref: {ref!r}")
    cache = cache_path(cache_root, source)
    if not cache.exists():
        if offline:
            raise MaintenanceError("No cached repository; run once without --offline")
        cache.mkdir(parents=True)
        git(cache, "init", "--bare", "--quiet")
    if not offline:
        git(cache, "fetch", "--quiet", "--depth=1", "--no-tags", url, ref)
        commit = git(cache, "rev-parse", "FETCH_HEAD^{commit}").decode().strip()
        git(cache, "update-ref", cache_ref(ref), commit)
    else:
        commit = git(cache, "rev-parse", cache_ref(ref) + "^{commit}").decode().strip()
    return cache, commit


def upstream_assets(cache: Path, commit: str, specs: dict) -> dict[str, dict[str, Asset]]:
    paths = [safe_relative(spec["path"]) for spec in specs.values()]
    if len(paths) != len(set(paths)):
        raise MaintenanceError("Two local skills refer to the same upstream directory")
    result = {name: {} for name in specs}
    archive = git(cache, "archive", "--format=tar", commit, "--", *paths)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar:
            name = member.name.rstrip("/")
            safe_relative(name)
            if member.isdir():
                continue
            if not member.isfile():
                raise MaintenanceError(f"Unsupported upstream file type: {member.name}")
            matches = [n for n, s in specs.items() if name.startswith(s["path"] + "/")]
            if len(matches) != 1:
                raise MaintenanceError(f"Ambiguous upstream path: {name}")
            target = matches[0]
            rel = safe_relative(name[len(specs[target]["path"]) + 1:])
            stream = tar.extractfile(member)
            if stream is None:
                raise MaintenanceError(f"Cannot read upstream file: {name}")
            # Git tracks only the executable bit; archive umasks can add group write.
            result[target][rel] = Asset(stream.read(), 0o755 if member.mode & 0o111 else 0o644)
    for name, assets in result.items():
        manifest = assets.get("SKILL.md")
        if manifest is None:
            raise MaintenanceError(f"Upstream skill has no SKILL.md: {name}")
        text = manifest.data.decode("utf-8")
        parts = text.split("---", 2)
        if not text.startswith("---\n") or len(parts) != 3:
            raise MaintenanceError(f"Invalid manifest frontmatter: {name}")
        match = re.search(r"^name:\s*([^\r\n]+)$", parts[1], re.MULTILINE)
        if match is None or match[1].strip("\"' ") != specs[name]["upstream_name"]:
            raise MaintenanceError(f"Unexpected upstream manifest name: {name}")
        if re.search(r"^description:\s*\S", parts[1], re.MULTILINE) is None:
            raise MaintenanceError(f"Manifest description is missing: {name}")
        if name != specs[name]["upstream_name"]:
            # Only rewrite frontmatter, leaving the upstream body intact.
            parts[1] = parts[1][:match.start()] + "name: " + name + parts[1][match.end():]
            assets["SKILL.md"] = Asset("---".join(parts).encode(), manifest.mode)
    return result


class Maintenance:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir.resolve()
        self.registry_path = self.state_dir / "skill-sources.json"
        self.runtime = self.state_dir / "skill-maintenance"

    @contextmanager
    def exclusive(self):
        self.runtime.mkdir(parents=True, exist_ok=True)
        with (self.runtime / "operation.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise MaintenanceError("Another skill maintenance command is running") from exc
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def registry(self) -> tuple[bytes, dict]:
        raw = self.registry_path.read_bytes()
        data = json.loads(raw)
        if data.get("version") != 1 or not isinstance(data.get("sources"), dict):
            raise MaintenanceError("Unsupported source registry")
        expected_root = (self.state_dir / "skills").resolve()
        if Path(data["skills_directory"]).resolve() != expected_root:
            raise MaintenanceError("Registry skills directory must be STATE_DIR/skills")
        seen = set()
        for source, record in data["sources"].items():
            if normalize_source(source) != source:
                raise MaintenanceError(f"Noncanonical source name: {source}")
            if not record.get("skills"):
                raise MaintenanceError(f"No registered skills: {source}")
            for name, spec in record["skills"].items():
                local_name(name)
                if name in seen:
                    raise MaintenanceError(f"Duplicate local skill: {name}")
                seen.add(name)
                safe_relative(spec["path"])
                local_name(spec["upstream_name"])
                for rel in spec["files"]:
                    safe_relative(rel)
        return raw, data

    def snapshot(self, source: str) -> tuple[Snapshot, dict]:
        raw, registry = self.registry()
        if source not in registry["sources"]:
            raise MaintenanceError(f"Source is not registered: {source}")
        lock = Path(registry["external_lock"])
        if lock.is_symlink():
            raise MaintenanceError("External lock file must be a regular file")
        assets = {
            name: read_assets(Path(registry["skills_directory"]) / name)
            for name in registry["sources"][source]["skills"]
        }
        return Snapshot(raw, lock.read_bytes() if lock.exists() else None, assets), registry

    def conflicts(self, source: str, snapshot: Snapshot, registry: dict) -> list[str]:
        specs = registry["sources"][source]["skills"]
        conflicts = []
        for name, assets in snapshot.skills.items():
            actual, expected = fingerprints(assets), specs[name]["files"]
            conflicts.extend(f"{name}/{rel}" for rel in sorted(actual.keys() | expected.keys())
                             if actual.get(rel) != expected.get(rel))
        if snapshot.external_lock is not None:
            external = json.loads(snapshot.external_lock)
            for name, spec in external.get("skills", {}).items():
                if spec.get("source") == source and name not in specs:
                    conflicts.append(f"Unmapped source skill in external lock: {name}")
        return conflicts

    def report(self, summary: dict, details: dict) -> dict:
        path = self.runtime / "reports" / (self.stamp() + ".json")
        summary = {**summary, "report": str(path)}
        atomic_write(path, json_bytes({"summary": summary, "details": details}))
        return summary

    @staticmethod
    def stamp() -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:6]

    def check(self, source: str) -> dict:
        snapshot, registry = self.snapshot(source)
        conflicts = self.conflicts(source, snapshot, registry)
        return self.report({"source": source, "status": "conflict" if conflicts else "verified",
                            "skills": len(snapshot.skills), "changed": 0, "conflicts": len(conflicts)},
                           {"conflicts": conflicts, "commit": registry["sources"][source]["commit"]})

    def update(self, source: str, cache_root: Path, ref: str | None, offline: bool, apply: bool) -> dict:
        before, registry = self.snapshot(source)
        conflicts = self.conflicts(source, before, registry)
        summary = {"source": source, "skills": len(before.skills), "changed": 0, "conflicts": len(conflicts)}
        if conflicts:
            return self.report({**summary, "status": "conflict"}, {"conflicts": conflicts})
        record = registry["sources"][source]
        cache, commit = fetch_commit(cache_root, source, record["url"], ref or record["default_ref"], offline)
        desired = upstream_assets(cache, commit, record["skills"])
        for name, assets in desired.items():
            for rel, asset in list(assets.items()):
                installed = before.skills[name].get(rel)
                if installed is not None:
                    # Preserve local read/write permissions; Git controls executable bits.
                    assets[rel] = Asset(asset.data, (installed.mode & ~0o111) | (asset.mode & 0o111))
        changes = {name: changed_files(before.skills[name], assets) for name, assets in desired.items()}
        changes = {name: paths for name, paths in changes.items() if paths}
        summary.update(changed=len(changes), commit=commit)
        record["commit"] = commit
        for name, assets in desired.items():
            record["skills"][name]["files"] = fingerprints(assets)
        after_lock = before.external_lock
        if before.external_lock is not None:
            external = json.loads(before.external_lock)
            for name, spec in record["skills"].items():
                entry = external.get("skills", {}).get(name)
                if entry and entry.get("source") == source:
                    tree = git(cache, "rev-parse", commit + ":" + spec["path"]).decode().strip()
                    if entry.get("skillFolderHash") != tree or entry.get("skillPath") != spec["path"] + "/SKILL.md":
                        entry.update(skillFolderHash=tree, skillPath=spec["path"] + "/SKILL.md",
                                     updatedAt=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
            # Preserve the exact bytes for a no-op and preserve unrelated entries on a real update.
            if external != json.loads(before.external_lock):
                after_lock = json_bytes(external)
        after_registry = before.registry if registry == json.loads(before.registry) else json_bytes(registry)
        after = Snapshot(after_registry, after_lock, desired)
        metadata_changed = after_registry != before.registry or after_lock != before.external_lock
        details = {"changes": changes, "metadata_changed": metadata_changed, "offline": offline}
        if not changes and not metadata_changed:
            return self.report({**summary, "status": "current"}, details)
        if not apply:
            return self.report({**summary, "status": "preview"}, details)
        backup = self.transact(source, before, after)
        return self.report({**summary, "status": "updated", "backup": str(backup)}, details)

    def write_snapshot(self, snapshot: Snapshot) -> None:
        registry = json.loads(snapshot.registry)
        root = Path(registry["skills_directory"])
        for name, assets in snapshot.skills.items():
            current = read_assets(root / name)
            # Remove obsolete files first so file/directory transitions are possible.
            for rel in current.keys() - assets.keys():
                (root / name / rel).unlink()
            for path in sorted((root / name).rglob("*"), key=lambda p: len(p.parts), reverse=True):
                if path.is_dir() and not any(path.iterdir()):
                    path.rmdir()
            for rel, asset in assets.items():
                if current.get(rel) != asset:
                    atomic_write(root / name / rel, asset.data, asset.mode)
        lock = Path(registry["external_lock"])
        if snapshot.external_lock is None:
            lock.unlink(missing_ok=True)
        elif not lock.exists() or lock.read_bytes() != snapshot.external_lock:
            atomic_write(lock, snapshot.external_lock, lock.stat().st_mode & 0o777 if lock.exists() else 0o600)
        if self.registry_path.read_bytes() != snapshot.registry:
            atomic_write(self.registry_path, snapshot.registry)

    def transact(self, source: str, before: Snapshot, after: Snapshot) -> Path:
        current, _ = self.snapshot(source)
        if snapshot_fingerprint(current) != snapshot_fingerprint(before):
            raise MaintenanceError("Installed skills or metadata changed during preparation")
        backup = self.state_dir / "skill-backups" / ("managed-" + self.stamp())
        backup.mkdir(parents=True)
        atomic_write(backup / "registry.json", before.registry)
        if before.external_lock is not None:
            atomic_write(backup / "external-lock.json", before.external_lock)
        for name, assets in before.skills.items():
            for rel, asset in assets.items():
                atomic_write(backup / "skills" / name / rel, asset.data, asset.mode)
        manifest = {"kind": "skill-maintenance-backup", "version": 1, "source": source,
                    "state_dir": str(self.state_dir), "status": "prepared",
                    "before": snapshot_fingerprint(before), "after": snapshot_fingerprint(after)}
        atomic_write(backup / "manifest.json", json_bytes(manifest))
        current, _ = self.snapshot(source)
        if snapshot_fingerprint(current) != snapshot_fingerprint(before):
            manifest["status"] = "aborted"
            atomic_write(backup / "manifest.json", json_bytes(manifest))
            raise MaintenanceError("Installed skills or metadata changed while creating the backup")
        manifest["status"] = "applying"
        atomic_write(backup / "manifest.json", json_bytes(manifest))
        try:
            self.write_snapshot(after)
            installed, _ = self.snapshot(source)
            if snapshot_fingerprint(installed) != snapshot_fingerprint(after):
                raise MaintenanceError("Post-update verification failed")
            manifest["status"] = "completed"
            atomic_write(backup / "manifest.json", json_bytes(manifest))
        except BaseException as error:
            try:
                self.write_snapshot(before)
                restored, _ = self.snapshot(source)
                if snapshot_fingerprint(restored) != snapshot_fingerprint(before):
                    raise MaintenanceError("Rollback verification failed")
                manifest["status"] = "rolled-back"
                atomic_write(backup / "manifest.json", json_bytes(manifest))
            except BaseException as rollback_error:
                raise MaintenanceError(f"Rollback needs recovery from {backup}: {rollback_error}") from error
            raise MaintenanceError(f"Update failed and was rolled back; backup: {backup}; reason: {error}") from error
        return backup

    def restore(self, backup: Path, apply: bool) -> dict:
        manifest = json.loads((backup / "manifest.json").read_bytes())
        if (manifest.get("kind") != "skill-maintenance-backup" or manifest.get("version") != 1
                or manifest.get("state_dir") != str(self.state_dir)):
            raise MaintenanceError("Backup does not belong to this skill maintenance registry")
        source = normalize_source(manifest["source"])
        current, registry = self.snapshot(source)
        old_registry = (backup / "registry.json").read_bytes()
        old_data = json.loads(old_registry)
        if (old_data["skills_directory"] != registry["skills_directory"]
                or old_data["external_lock"] != registry["external_lock"]
                or set(old_data["sources"][source]["skills"]) != set(current.skills)):
            raise MaintenanceError("Backup paths or registered skills no longer match")
        restored = Snapshot(old_registry,
                            (backup / "external-lock.json").read_bytes() if manifest["before"]["external_lock"] is not None else None,
                            {name: read_assets(backup / "skills" / local_name(name)) for name in current.skills})
        if snapshot_fingerprint(restored) != manifest["before"]:
            raise MaintenanceError("Backup contents failed checksum verification")
        actual = snapshot_fingerprint(current)
        if manifest["status"] == "applying":
            # A terminated process can leave a mixture of the original and replacement files.
            for name, assets in actual["skills"].items():
                before, after = manifest["before"]["skills"][name], manifest["after"]["skills"][name]
                for rel in assets.keys() | before.keys() | after.keys():
                    if assets.get(rel) not in (before.get(rel), after.get(rel)):
                        raise MaintenanceError(f"Edited since interrupted update: {name}/{rel}")
            for key in ("registry", "external_lock"):
                if actual[key] not in (manifest["before"][key], manifest["after"][key]):
                    raise MaintenanceError("Metadata changed after interrupted update")
        elif manifest["status"] != "completed" or actual != manifest["after"]:
            raise MaintenanceError("Skills or metadata changed since this backup; refusing to overwrite edits")
        count = sum(bool(changed_files(current.skills[n], a)) for n, a in restored.skills.items())
        summary = {"source": source, "skills": len(restored.skills), "changed": count, "conflicts": 0}
        if not apply:
            return self.report({**summary, "status": "restore-preview"}, {"restore_from": str(backup)})
        recovery_backup = self.transact(source, current, restored)
        return self.report({**summary, "status": "restored", "backup": str(recovery_backup)}, {"restore_from": str(backup)})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    parser.add_argument("--cache-dir", type=Path, default=Path.home() / ".cache/skill-maintenance")
    parser.add_argument("--json", action="store_true", help="Print compact machine-readable summary")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="Verify source coverage and local files without network access")
    check.add_argument("source")
    update = commands.add_parser("update", help="Preview an update; use --apply to install it")
    update.add_argument("source")
    update.add_argument("--ref", help="Branch, tag or commit; defaults to the registered ref")
    update.add_argument("--offline", action="store_true", help="Use the cached commit without checking upstream freshness")
    update.add_argument("--apply", action="store_true")
    restore = commands.add_parser("restore", help="Preview restoring a backup; use --apply to restore it")
    restore.add_argument("backup", type=Path)
    restore.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    manager = Maintenance(args.state_dir)
    try:
        with manager.exclusive():
            if args.command == "restore":
                summary = manager.restore(args.backup.resolve(), args.apply)
            elif args.command == "check":
                summary = manager.check(normalize_source(args.source))
            else:
                summary = manager.update(normalize_source(args.source), args.cache_dir, args.ref, args.offline, args.apply)
        if args.json:
            print(json.dumps(summary, ensure_ascii=False))
        else:
            print(f"{summary['source']}: {summary['status']}; {summary['skills']} skills, "
                  f"{summary['changed']} changed, {summary['conflicts']} conflicts")
            for key in ("commit", "backup", "report"):
                if key in summary:
                    print(f"{key.capitalize()}: {summary[key]}")
        return 1 if summary["conflicts"] else 0
    except (MaintenanceError, OSError, ValueError, KeyError, TypeError, tarfile.TarError) as exc:
        summary = manager.report({"status": "error", "error": str(exc)}, {"command": args.command})
        if args.json:
            print(json.dumps(summary, ensure_ascii=False))
        else:
            concise_error = str(exc).splitlines()[0][:300]
            print(f"Error: {concise_error}\nReport: {summary['report']}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
