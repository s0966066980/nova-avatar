# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OLD_BRAND = "Linly-Talker-Stream"
LEGACY_VISIBLE_BRAND = re.compile(r"\bLinly(?:[-_ ]Talker(?:[-_ ]Stream)?)?\b", re.IGNORECASE)


class BrandingComplianceTests(unittest.TestCase):
    def test_project_metadata_uses_nova_avatar(self):
        project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertRegex(project, r'(?m)^name = "nova-avatar"$')
        self.assertRegex(project, r'(?m)^version = "1\.0\.0"$')
        self.assertIn('{ name = "HongXian0903" }', project)
        self.assertIn(
            'Repository = "https://github.com/s0966066980/nova-avatar"',
            project,
        )

        package = json.loads((ROOT / "web/package.json").read_text(encoding="utf-8"))
        self.assertEqual(package["name"], "nova-avatar-web")
        self.assertEqual(package["author"], "HongXian0903")
        self.assertEqual(package["license"], "Apache-2.0")

    def test_legal_attribution_and_restrictions_are_present(self):
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
        third_party = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

        self.assertIn("Apache License", license_text)
        for required in ("Kedreamix", OLD_BRAND, "LiveTalking", "Apache License"):
            self.assertIn(required, notice)
        self.assertIn("Copyright (c) 2024 Tencent Music Entertainment Group", third_party)
        self.assertRegex(third_party, r"Wav2Lip[\s\S]+Research / Non-commercial")
        self.assertRegex(third_party, r"Wav2Lip[\s\S]+not permitted")
        self.assertTrue((ROOT / "third_party/licenses/MuseTalk-LICENSE.txt").is_file())

    def test_user_visible_surfaces_do_not_show_old_brand(self):
        files = (
            "web/index.html",
            "web/stage.html",
            "web/answer-board.prototype.html",
            "web/board-interactive-test.html",
            "web/console-uiux-prototype.html",
            "web/src/App.vue",
            "web/src/components/InteractionPanel.vue",
            "web/src/components/SettingsPanel.vue",
            "web/src/locales/en-US.js",
            "web/src/locales/zh-CN.js",
            "web/src/locales/zh-TW.js",
            "config/prompt_en.txt",
        )
        for relative in files:
            text = (ROOT / relative).read_text(encoding="utf-8")
            text = re.sub(r"\A\s*<!--.*?-->\s*", "", text, count=1, flags=re.DOTALL)
            text = re.sub(
                r"\A(?:// (?:Derived from|Modified by)[^\n]*\n)+\s*",
                "",
                text,
            )
            text = "\n".join(
                line for line in text.splitlines() if "legacyStorageKey" not in line
            )
            with self.subTest(file=relative):
                self.assertNotRegex(text, LEGACY_VISIBLE_BRAND)

        self.assertTrue((ROOT / "README.md").read_text(encoding="utf-8").startswith("# Nova Avatar\n"))
        self.assertIn("<title>Nova Avatar</title>", (ROOT / "web/index.html").read_text(encoding="utf-8"))

    def test_wav2lip_is_labeled_non_commercial_in_runtime_and_ui(self):
        catalog = (ROOT / "src/avatars/catalog.py").read_text(encoding="utf-8")
        settings = (ROOT / "web/src/components/SettingsPanel.vue").read_text(encoding="utf-8")
        wav2lip_package = (ROOT / "src/avatars/wav2lip/pyproject.toml").read_text(encoding="utf-8")

        for text in (catalog, settings):
            self.assertIn("Wav2Lip (Research / Non-commercial)", text)
        self.assertIn("nova-avatar-wav2lip-research", wav2lip_package)
        self.assertNotIn('license = "Apache-2.0"', wav2lip_package)


if __name__ == "__main__":
    unittest.main()
