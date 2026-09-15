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

    def test_commercial_profile_uses_the_supported_avatar_path(self):
        profile = ROOT / "config/config_commercial.yaml"
        cfg = integration_check.load_config(str(profile))
        self.assertEqual(cfg.model.type, "musetalk")
        self.assertNotEqual(cfg.model.type, "wav2lip")

    def test_required_project_contract_includes_legal_and_audit_artifacts(self):
        self.assertIn("NOTICE", integration_check.REQUIRED_FILES)
        self.assertIn("docs/source-attribution-audit.md", integration_check.REQUIRED_FILES)
        self.assertIn("docs/software-stack.md", integration_check.REQUIRED_FILES)


if __name__ == "__main__":
    unittest.main()
