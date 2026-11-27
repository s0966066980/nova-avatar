#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Regenerate contracts/openapi/*.json from the Pydantic models, or verify them.

    python scripts/generate-openapi.py          # rewrite the committed documents
    python scripts/generate-openapi.py --check  # exit 1 if they differ from the models
"""
from __future__ import annotations

import sys
from pathlib import Path

from nova_contracts.openapi import documents, render

OUTPUT = Path(__file__).resolve().parents[1] / "contracts" / "openapi"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    stale = []
    for name, document in documents().items():
        text, path = render(document), OUTPUT / name
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    if stale:
        print("contracts/openapi is out of date: " + ", ".join(stale))
        print("run: uv run --no-sync python scripts/generate-openapi.py")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
