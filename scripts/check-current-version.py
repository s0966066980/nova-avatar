#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Run the current release baseline locally and retain reviewable evidence.

Requires an already prepared, frozen CUDA environment and Node 22 on PATH.
Live deployment checks are separate; this command never starts model services.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET

import yaml

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests/current-version-baseline.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("all", "environment", "static", "integration", "python", "web", "build"), default="all")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    baseline = json.loads(BASELINE.read_text())
    now = lambda: dt.datetime.now(dt.timezone.utc).isoformat()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = (args.output or ROOT / ".scratch/current-version-baseline" / stamp).resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {"started_at": now(), "stage": args.stage, "baseline": baseline, "steps": []}

    def save() -> None:
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    def run(name: str, argv: list[str], *, web: bool = False, extra: dict | None = None, advisory: bool = False) -> bool:
        env = os.environ.copy()
        env.update(extra or {})
        item = {"name": name, "argv": argv, "cwd": str(ROOT / "web" if web else ROOT), "environment_overrides": extra or {}, "started_at": now(), "advisory": advisory, "log": name + ".log"}
        try:
            with (output / item["log"]).open("w") as log:
                result = subprocess.run(argv, cwd=item["cwd"], env=env, stdout=log, stderr=subprocess.STDOUT)
            item["exit_code"] = result.returncode
        except OSError as exc:
            (output / item["log"]).write_text(str(exc) + "\n")
            item["exit_code"] = 127
        item["ended_at"] = now()
        report["steps"].append(item)
        save()
        print(f"{name}: {'PASS' if item['exit_code'] == 0 else 'ADVISORY' if advisory else 'FAIL'}", flush=True)
        return item["exit_code"] == 0

    def finish() -> int:
        report["ended_at"] = now()
        report["passed"] = all(s["exit_code"] == 0 or s["advisory"] for s in report["steps"]) and not report.get("validation_errors")
        save()
        hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.iterdir()) if p.is_file() and p.name != "sha256.json"}
        (output / "sha256.json").write_text(json.dumps(hashes, indent=2) + "\n")
        print(f"Evidence: {output}", flush=True)
        return 0 if report["passed"] else 1

    for name, argv in (("source-head", ["git", "rev-parse", "HEAD"]), ("source-status", ["git", "status", "--porcelain=v1"]), ("source-diff", ["git", "diff", "HEAD", "--"])):
        run(name, argv)
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.decode().split("\0")
    inputs = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in tracked if p and (ROOT / p).is_file()}
    # New baseline files may not have been committed yet.
    for path in (BASELINE, Path(__file__).resolve()):
        inputs[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    (output / "source-sha256.json").write_text(json.dumps(inputs, indent=2) + "\n")
    config = yaml.safe_load((ROOT / "config/config.yaml").read_text())
    errors = []
    if tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"] != baseline["project_version"]:
        errors.append("Project version changed; review the baseline")
    for dotted, expected in baseline["defaults"].items():
        value = config
        for key in dotted.split("."):
            value = value.get(key) if isinstance(value, dict) else None
        if value != expected:
            errors.append(f"Default {dotted}: expected {expected!r}, found {value!r}")
    if not os.getenv("UV_PROJECT_ENVIRONMENT"):
        errors.append("Set UV_PROJECT_ENVIRONMENT to the prepared isolated CUDA environment")
    report["validation_errors"] = errors
    if errors:
        return finish()
    cuda_code = f'''import json,sys,torch
assert '.'.join(map(str,sys.version_info[:2])) == {baseline['python_minor']!r}
assert torch.__version__ == {baseline['torch_version']!r}
assert torch.version.cuda == {baseline['cuda_build']!r} and torch.cuda.is_available()
a=torch.arange(64,dtype=torch.float32).reshape(8,8)
g=a.to('cuda'); result=g@g
assert result.is_cuda and torch.equal(result.cpu(),a@a)
torch.cuda.synchronize()
print(json.dumps(dict(python=sys.version,torch=torch.__version__,cuda=torch.version.cuda,gpu=torch.cuda.get_device_name(0))))
'''
    prerequisites = [run("uv-version", ["uv", "--version"]), run("lock-check", ["uv", "lock", "--check"]), run("frozen-environment", ["uv", "sync", "--frozen", "--check", "--group", "dev", "--group", "ci", "--extra", "vad"]), run("cuda", [sys.executable, "-c", cuda_code]), run("node-version", ["node", "--version"])]
    node = (output / "node-version.log").read_text().strip()
    if not node.startswith(f"v{baseline['node_major']}."):
        errors.append(f"Node {baseline['node_major']} required; found {node!r}")
    if not all(prerequisites) or errors:
        return finish()
    run("python-packages", ["uv", "pip", "freeze", "--python", sys.executable])
    run("npm-version", ["npm", "--version"])
    if args.stage in {"all", "static"}:
        run("ruff", ["uv", "run", "--no-sync", "ruff", "check", "."])
        run("pyright", ["uv", "run", "--no-sync", "pyright"])
    if args.stage in {"all", "integration"}:
        run("offline-integration", [sys.executable, "scripts/check-integration.py"], extra={"NOVA_AVATAR_RUNTIME_OVERRIDES_ENABLED": "0"})
    if args.stage in {"all", "python"}:
        command = ["uv", "run", "--no-sync", "pytest"]
        run("python-collection", command + ["--collect-only", "-q", "-m", baseline["python_selection"]])
        run("python-tests", command + ["-v", "-ra", "--durations=20", "-m", baseline["python_selection"], "--junitxml=" + str(output / "python.xml")])
        if (output / "python.xml").exists():
            cases = list(ET.parse(output / "python.xml").getroot().iter("testcase"))
            counts = {"collected": len(cases), "skipped": sum(c.find("skipped") is not None for c in cases), "failed": sum(c.find("failure") is not None or c.find("error") is not None for c in cases)}
            report["python"] = counts
            if not cases or counts["skipped"] > baseline["max_skipped"] or counts["failed"]:
                errors.append("Primary Python baseline requires executed cases, zero skips and zero failures")
        else:
            errors.append("Missing Python JUnit report")
    if args.stage in {"all", "static", "web", "build"}:
        installed = run("npm-ci", ["npm", "ci"], web=True)
        if installed:
            run("npm-audit", ["npm", "audit", "--omit=dev"], web=True, advisory=True)
            if args.stage in {"all", "static"}:
                run("eslint", ["npm", "run", "lint"], web=True)
            if args.stage in {"all", "web"}:
                run("web-tests", ["npm", "test"], web=True, extra={"CI": "1"})
                summary = (output / "web-tests.log").read_text()
                counts = {key: re.findall(rf"(?:#|ℹ)\s+{key}\s+(\d+)", summary) for key in ("tests", "fail", "skipped")}
                if any(not values for values in counts.values()) or int(counts["tests"][-1]) == 0 or int(counts["fail"][-1]) != 0 or int(counts["skipped"][-1]) != 0:
                    errors.append("Frontend requires a test summary, zero failures and zero skips")
                else:
                    report["web"] = {key: int(value[-1]) for key, value in counts.items()}
            if args.stage in {"all", "build"}:
                run("web-build", ["npm", "run", "build"], web=True)
    return finish()


if __name__ == "__main__":
    raise SystemExit(main())
