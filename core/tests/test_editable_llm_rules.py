import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.config.schema import Config, ReplyRulesConfig
from src.config.overrides import load_runtime_overrides, persist_runtime_overrides
from src.llm.rules import default_rules, snapshot_from_config, validate_rules
from src.server.runtime_settings import SettingsError, apply_reply_rules, reply_rules_snapshot


class EditableRuleTests(unittest.TestCase):
    def test_defaults_fill_empty_dataclass(self):
        config = Config()
        snapshot = snapshot_from_config(config)
        self.assertEqual(snapshot.revision, 1)
        self.assertEqual(snapshot.activation, default_rules()["activation"])

    def test_default_activation_uses_board_for_steps_and_processes(self):
        activation = default_rules()["activation"]
        self.assertIn("兩個或以上步驟、流程、階段", activation)
        self.assertIn("一個流程裡的多個步驟", activation)
        self.assertIn("或多個不同流程", activation)

    def test_validation_rejects_blank_and_overlong_content(self):
        defaults = default_rules()
        with self.assertRaises(ValueError):
            validate_rules({**defaults, "speech": "   "})
        with self.assertRaises(ValueError):
            validate_rules({**defaults, "board": "x" * 12001})

    def test_apply_persists_and_increments_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            override_path = Path(tmp) / "runtime_overrides.yaml"
            config = Config()
            config.llm.reply_rules = ReplyRulesConfig(**default_rules())
            values = {**default_rules(), "speech": "本輪只用一句話回答。"}
            with patch("src.config.overrides.RUNTIME_OVERRIDES_FILE", override_path):
                result = apply_reply_rules(config, values, expected_revision=1)
                persisted = load_runtime_overrides()
            self.assertEqual(result["applied_revision"], 2)
            self.assertEqual(persisted["llm"]["reply_rules"]["revision"], 2)
            self.assertEqual(persisted["llm"]["reply_rules"]["speech"], values["speech"])

    def test_conflict_keeps_current_rules(self):
        config = Config()
        before = snapshot_from_config(config)
        with self.assertRaises(SettingsError) as caught:
            apply_reply_rules(config, default_rules(), expected_revision=999)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(snapshot_from_config(config), before)

    def test_snapshot_and_defaults_are_exposed_separately(self):
        data = reply_rules_snapshot(Config())
        self.assertEqual(data["rules"]["revision"], 1)
        self.assertEqual(data["defaults"]["revision"], 1)
        self.assertIn("max_rule_chars", data["limits"])


if __name__ == "__main__":
    unittest.main()
