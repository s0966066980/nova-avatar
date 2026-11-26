#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Write contracts/openapi/<layer>.json from the contracts' ``HTTP_API`` declarations.

Every ``nova_contracts`` module that declares ``HTTP_API`` gets one document
named after the module. ``--check`` writes nothing and exits 1 when a
committed document is missing, stale or no longer declared (CI runs it).
"""
from __future__ import annotations

import argparse
import importlib
import json
import pkgutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Also run from a checkout whose venv has no nova-contracts installed.
sys.path.insert(0, str(ROOT / "contracts"))

import nova_contracts  # noqa: E402
from nova_contracts.http import openapi_document  # noqa: E402

DEFAULT_OUT = ROOT / "contracts" / "openapi"


def documents() -> dict[str, str]:
    """``<module>.json`` -> its document text, for each contract module with ``HTTP_API``."""
    generated = {}
    for module in sorted(pkgutil.iter_modules(nova_contracts.__path__), key=lambda m: m.name):
        api = getattr(importlib.import_module(f"nova_contracts.{module.name}"), "HTTP_API", None)
        if api is not None:
            text = json.dumps(openapi_document(api), indent=2, ensure_ascii=False)
            generated[f"{module.name}.json"] = text + "\n"
    return generated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="fail when the committed documents differ; write nothing")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    generated = documents()
    existing = {path.name for path in args.out.glob("*.json")} if args.out.is_dir() else set()
    if args.check:
        problems = [f"{name}: missing" for name in sorted(set(generated) - existing)]
        problems += [f"{name}: stale" for name in sorted(set(generated) & existing)
                     if (args.out / name).read_text("utf-8") != generated[name]]
        problems += [f"{name}: no contract module declares it"
                     for name in sorted(existing - set(generated))]
        for problem in problems:
            print(f"contracts/openapi/{problem}")
        if problems:
            print("Run: uv run --no-sync python scripts/generate_openapi.py")
            return 1
        print(f"OpenAPI documents are current: {', '.join(sorted(generated))}")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    for name in sorted(existing - set(generated)):
        (args.out / name).unlink()
    for name, text in generated.items():
        (args.out / name).write_text(text, "utf-8")
        print(f"wrote contracts/openapi/{name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
