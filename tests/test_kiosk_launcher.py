# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The kiosk launcher opens the stage in kiosk mode without needing a click."""
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "start-kiosk.sh"


def _dry_run(*args: str, **env: str) -> str:
    result = subprocess.run(
        ["bash", str(SCRIPT), *args],
        env={**os.environ, "NOVA_KIOSK_DRY_RUN": "1", "NOVA_KIOSK_BROWSER": "chromium", **env},
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    return result.stdout.strip()


class KioskLauncherTests(unittest.TestCase):
    def test_default_config_opens_the_https_stage_with_the_kiosk_marker(self):
        command = _dry_run()
        self.assertTrue(command.endswith("https://localhost:3000/stage.html?kiosk=1"), command)

    def test_config_without_ssl_uses_http(self):
        config = ROOT / ".pytest-kiosk-no-ssl.yaml"
        config.write_text("app:\n  ssl: false\n", encoding="utf-8")
        self.addCleanup(config.unlink)
        command = _dry_run(config.name)
        self.assertTrue(command.endswith("http://localhost:3000/stage.html?kiosk=1"), command)

    def test_browser_is_full_screen_and_skips_the_click_requirements(self):
        command = _dry_run().split()
        for flag in (
            "--kiosk",
            "--autoplay-policy=no-user-gesture-required",
            "--use-fake-ui-for-media-stream",
            "--allow-insecure-localhost",
        ):
            self.assertIn(flag, command)

    def test_profile_is_separate_from_the_users_browser_and_ignored_by_git(self):
        command = _dry_run()
        self.assertIn(f"--user-data-dir={ROOT}/.local/kiosk-profile", command)
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".local/kiosk-profile/", gitignore)

    def test_environment_overrides_url_and_profile(self):
        command = _dry_run(NOVA_KIOSK_URL="https://venue.example/stage.html?kiosk=1", NOVA_KIOSK_PROFILE="/tmp/profile")
        self.assertIn("--user-data-dir=/tmp/profile", command)
        self.assertTrue(command.endswith("https://venue.example/stage.html?kiosk=1"), command)

    def test_missing_config_fails_with_a_clear_message(self):
        result = subprocess.run(
            ["bash", str(SCRIPT), "no-such-config.yaml"],
            env={**os.environ, "NOVA_KIOSK_DRY_RUN": "1", "NOVA_KIOSK_BROWSER": "chromium"},
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("找不到設定檔", result.stderr)


if __name__ == "__main__":
    unittest.main()
