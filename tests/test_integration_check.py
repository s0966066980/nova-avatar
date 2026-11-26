# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check-integration.py"
SPEC = importlib.util.spec_from_file_location("integration_check", SCRIPT)
integration_check = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(integration_check)


class IntegrationCheckTests(unittest.TestCase):
    def test_parse_args_defaults_to_the_offline_check(self):
        args = integration_check.parse_args([])
        self.assertIsNone(args.config)
        self.assertFalse(args.smoke)
        self.assertIsNone(args.output)

    def test_required_project_contract_includes_legal_and_audit_artifacts(self):
        self.assertIn("NOTICE", integration_check.REQUIRED_FILES)
        self.assertIn("docs/source-attribution-audit.md", integration_check.REQUIRED_FILES)
        self.assertIn("docs/software-stack.md", integration_check.REQUIRED_FILES)

    def test_notice_audit_requires_the_matcha_voice_model_entries(self):
        notices = integration_check.REQUIRED_FILES["THIRD_PARTY_NOTICES.md"]
        for text in ("sherpa-onnx", "dengcunqin/matcha_tts_zh_en_20251010", "zh-tw-hsiaochen-edge"):
            self.assertIn(text, notices)
        self.assertIn("SHA-256", integration_check.REQUIRED_FILES["docs/voice-models.md"])

    def test_runtime_module_contract_covers_selected_optional_engines(self):
        self.assertEqual(integration_check.RUNTIME_MODULES["musetalk"], ("einops", "ffmpeg"))


if __name__ == "__main__":
    unittest.main()
