# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The kiosk launcher opens the stage in kiosk mode without needing a click."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
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


def _launch(profile: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    """Run the launcher for real with a browser that exits at once."""
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env={**os.environ, "NOVA_KIOSK_BROWSER": "true", "NOVA_KIOSK_PROFILE": str(profile),
             "NOVA_KIOSK_WAIT_SECONDS": "0", **env},
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )


def _microphone_preferences(profile: Path) -> tuple[dict, object]:
    preferences = json.loads((profile / "Default" / "Preferences").read_text(encoding="utf-8"))
    content = preferences["profile"]
    return content["content_settings"]["exceptions"]["media_stream_mic"], content["default_content_setting_values"]["media_stream_mic"]


class KioskLauncherTests(unittest.TestCase):
    def test_default_config_opens_the_backend_served_https_stage_with_the_kiosk_marker(self):
        command = _dry_run()
        self.assertTrue(command.endswith("https://localhost:8010/stage.html?kiosk=1"), command)

    def test_config_without_ssl_uses_http(self):
        config = ROOT / ".pytest-kiosk-no-ssl.yaml"
        config.write_text("app:\n  ssl: false\n", encoding="utf-8")
        self.addCleanup(config.unlink)
        command = _dry_run(config.name)
        self.assertTrue(command.endswith("http://localhost:8010/stage.html?kiosk=1"), command)
        self.assertNotIn("--allow-insecure-localhost", command.split())

    def test_browser_is_full_screen_and_skips_the_click_requirements(self):
        command = _dry_run().split()
        for flag in (
            "--kiosk",
            "--autoplay-policy=no-user-gesture-required",
            "--allow-insecure-localhost",
        ):
            self.assertIn(flag, command)

    def test_microphone_is_not_granted_to_every_page(self):
        self.assertNotIn("--use-fake-ui-for-media-stream", _dry_run().split())

    def test_kiosk_profile_allows_the_microphone_only_for_the_stage_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile"
            _launch(profile)
            allowed, default = _microphone_preferences(profile)
            self.assertEqual(allowed, {"https://localhost:8010,*": {"setting": 1}})
            self.assertEqual(default, 2)

    def test_kiosk_profile_keeps_other_preferences_and_drops_stale_microphone_grants(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile"
            (profile / "Default").mkdir(parents=True)
            (profile / "Default" / "Preferences").write_text(json.dumps({
                "browser": {"window_placement": {"maximized": True}},
                "profile": {"content_settings": {"exceptions": {
                    "media_stream_mic": {"https://localhost:3000,*": {"setting": 1}},
                    "notifications": {"https://example.test,*": {"setting": 2}},
                }}},
            }), encoding="utf-8")
            _launch(profile)
            preferences = json.loads((profile / "Default" / "Preferences").read_text(encoding="utf-8"))
            self.assertEqual(preferences["browser"], {"window_placement": {"maximized": True}})
            exceptions = preferences["profile"]["content_settings"]["exceptions"]
            self.assertEqual(exceptions["media_stream_mic"], {"https://localhost:8010,*": {"setting": 1}})
            self.assertIn("notifications", exceptions)

    def test_dry_run_does_not_touch_the_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile"
            _dry_run(NOVA_KIOSK_PROFILE=str(profile))
            self.assertFalse(profile.exists())

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
