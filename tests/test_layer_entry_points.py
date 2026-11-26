# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The core reaches a converted layer only through its entry modules (ticket 07).

A converted layer has an import-linter ``protected`` contract whose id ends in
``-internals-private``: its internals may be imported only by the layer itself.
Its ``adapter`` and ``config_section`` modules are the entry points; the
package ``__init__`` re-exports nothing. These checks keep that contract from
going stale as modules are added.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
ENTRY_MODULES = ("adapter", "config_section")


def _private_contracts() -> list[dict]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    return [contract for contract in config["tool"]["importlinter"]["contracts"]
            if contract["id"].endswith("-internals-private")]


def _modules(package: str) -> set[str]:
    directory = ROOT.joinpath(*package.split("."))
    names = set()
    for path in directory.rglob("*.py"):
        parts = path.relative_to(ROOT).with_suffix("").parts
        names.add(".".join(parts[:-1] if parts[-1] == "__init__" else parts))
    return names


def _covered(module: str, protected: list[str]) -> bool:
    return any(module == name or module.startswith(name + ".") for name in protected)


def test_the_stt_layer_is_converted():
    assert "stt-internals-private" in {contract["id"] for contract in _private_contracts()}


@pytest.mark.parametrize("contract", _private_contracts(), ids=lambda contract: contract["id"])
def test_every_module_of_a_converted_layer_is_private_or_an_entry_point(contract):
    assert contract["type"] == "protected"
    layer = contract["allowed_importers"]
    entry_points = {f"{package}.{name}" for package in layer for name in ENTRY_MODULES}
    unprotected = {
        module
        for package in layer
        for module in _modules(package) - {package}
        if not _covered(module, contract["protected_modules"])
    }

    assert unprotected <= entry_points, "add these to protected_modules: " + ", ".join(
        sorted(unprotected - entry_points))


@pytest.mark.parametrize("contract", _private_contracts(), ids=lambda contract: contract["id"])
def test_a_converted_layer_package_reexports_nothing(contract):
    for package in contract["allowed_importers"]:
        init = ROOT.joinpath(*package.split("."), "__init__.py")
        tree = ast.parse(init.read_text("utf-8"))
        assert not [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))], (
            f"{package}/__init__.py imports; the core must use {package}.adapter")
