# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
import unittest
import warnings


ROOT = Path(__file__).resolve().parents[1]


def test_funasr_and_musetalk_have_reproducible_root_extras():
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'funasr = [\n    "funasr>=1.1",\n]' in project
    assert 'musetalk = [\n    "nova-avatar-musetalk",\n]' in project
    assert 'nova-avatar-musetalk = { path = "src/avatars/musetalk", editable = true }' in project


class AvatarEnvironmentTests(unittest.TestCase):
    def test_pkg_resources_is_available_for_openmmlab(self):
        """mmengine/mmpose still import pkg_resources while building MuseTalk roles."""
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                import pkg_resources  # noqa: F401
        except ModuleNotFoundError:
            self.fail(
                "MuseTalk role creation requires pkg_resources via mmengine/mmpose; "
                "install a setuptools version older than 82"
            )
