# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock


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
        raw = profile.read_text(encoding="utf-8").lower()
        for forbidden in ("wav2lip", "lfm2.5", "qwen3.5"):
            self.assertNotIn(forbidden, raw)

        cfg = integration_check.load_config(str(profile))
        self.assertEqual(cfg.model.type, "musetalk")
        self.assertNotEqual(cfg.model.type, "wav2lip")
        self.assertEqual(cfg.model.presentation_modes.get(cfg.model.avatar_id), "prerecorded")
        self.assertEqual(cfg.asr.type, "whisper")
        self.assertEqual(cfg.asr.model_size, "small")
        self.assertEqual(cfg.llm.provider, "llamacpp")
        self.assertEqual(cfg.llm.model, "gemma-4-E2B_q4_0-it")
        integration_check.check_commercial_profile()

    def test_required_project_contract_includes_legal_and_audit_artifacts(self):
        self.assertIn("NOTICE", integration_check.REQUIRED_FILES)
        self.assertIn("docs/source-attribution-audit.md", integration_check.REQUIRED_FILES)
        self.assertIn("docs/software-stack.md", integration_check.REQUIRED_FILES)
        self.assertIn("docs/models.md", integration_check.REQUIRED_FILES)
        self.assertIn("docs/commercial-release-checklist.md", integration_check.REQUIRED_FILES)
        integration_check.check_project_contract()

    def test_runtime_module_contract_covers_selected_optional_engines(self):
        self.assertEqual(integration_check.RUNTIME_MODULES["funasr"], ("funasr",))
        self.assertEqual(integration_check.RUNTIME_MODULES["musetalk"], ("einops", "ffmpeg"))

    def test_check_commercial_profile_rejects_drifted_model_or_presentation(self):
        fake_cfg = SimpleNamespace(
            model=SimpleNamespace(
                type="musetalk",
                avatar_id="musetalk_avatar1",
                presentation_modes={},
            ),
            asr=SimpleNamespace(type="whisper", model_size="small"),
            llm=SimpleNamespace(provider="llamacpp", model="gemma-4-E2B_q4_0-it"),
        )
        with mock.patch.object(integration_check, "load_config", return_value=fake_cfg):
            with self.assertRaisesRegex(RuntimeError, "prerecorded"):
                integration_check.check_commercial_profile()

        fake_cfg.model.presentation_modes = {"musetalk_avatar1": "prerecorded"}
        fake_cfg.llm.model = "qwen3.5:4b"
        with mock.patch.object(integration_check, "load_config", return_value=fake_cfg):
            with self.assertRaisesRegex(RuntimeError, "gemma-4-E2B_q4_0-it"):
                integration_check.check_commercial_profile()


if __name__ == "__main__":
    unittest.main()
