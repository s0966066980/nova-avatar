# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_funasr_and_musetalk_have_reproducible_root_extras():
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'funasr = [\n    "funasr>=1.1",\n]' in project
    assert 'musetalk = [\n    "nova-avatar-musetalk",\n]' in project
    assert 'nova-avatar-musetalk = { path = "src/avatars/musetalk", editable = true }' in project
