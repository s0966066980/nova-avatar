import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.config.schema import Config
from src.config.loader import dict_to_config
from src.config.overrides import load_runtime_overrides, persist_runtime_overrides
from src.llm.base import load_system_prompt
from src.llm.prompts import AUTO_MODE_PROMPT, compose_system_prompt
from src.llm.router import ReplyMode
from src.server.runtime_settings import apply_llm_model, current_snapshot


class AssistantProfileTests(unittest.TestCase):
    def _profile(self, name="ITRI 助手", prompt="你是 ITRI 助手。"):
        return {
            "assistant_name": name,
            "system_prompt": prompt,
            "output_locale": "zh-TW",
            "enforce_output_locale": True,
            "forbidden_self_names": ["Linly", "Linly 數位人助手"],
        }

    def test_profile_is_the_prompt_source_and_protocol_has_no_identity(self):
        profile = self._profile()
        prompt = compose_system_prompt(
            profile["system_prompt"], ReplyMode.AUTO,
            assistant_name=profile["assistant_name"],
            restriction_prompt="不得虛構未設定能力。",
        )
        self.assertIn("ITRI 助手", prompt)
        self.assertIn("不得虛構未設定能力。", prompt)
        self.assertIn("不要在開頭自我介紹", prompt)
        self.assertNotIn("Linly 數位人助手", prompt)
        self.assertNotIn("Linly", AUTO_MODE_PROMPT)
        self.assertNotIn("ITRI", AUTO_MODE_PROMPT)

    def test_profile_update_resets_sessions_but_length_update_does_not(self):
        config = Config()
        config.llm.provider = "ollama"
        config.llm.base_url = "http://localhost:11434/v1"
        session = SimpleNamespace(
            clear_history=unittest.mock.Mock(),
            set_last_board=unittest.mock.Mock(),
        )
        with patch("src.server.runtime_settings.persist_runtime_overrides"), patch(
            "src.llm.service._session_llm_instances", {1: session}
        ), patch("src.server.runtime_settings.ensure_server"):
            first = apply_llm_model(config, "model", "ollama", assistant_profile=self._profile())
            self.assertTrue(first["history_reset"])
            self.assertEqual(session.clear_history.call_count, 1)
            second = apply_llm_model(config, "model", "ollama", response_max_chars=180)
        self.assertFalse(second["history_reset"])
        self.assertEqual(session.clear_history.call_count, 1)

    def test_profile_persists_in_snapshot_and_legacy_value_is_read_only_migration(self):
        config = Config()
        config.llm.system_prompt = "舊設定"
        self.assertEqual(load_system_prompt(config), "舊設定")
        config.llm.assistant_profile.system_prompt = "新設定"
        config.llm.assistant_profile.assistant_name = "新助手"
        with patch("src.server.runtime_settings.list_avatar_characters", return_value=[]), patch(
            "src.server.runtime_settings.list_engines", return_value=[]
        ):
            snapshot = current_snapshot(config)
        self.assertEqual(snapshot["llm"]["assistant_profile"]["system_prompt"], "新設定")
        self.assertEqual(snapshot["llm"]["assistant_profile"]["assistant_name"], "新助手")

    def test_profile_round_trips_through_runtime_overrides(self):
        config = Config()
        profile = self._profile()
        for key, value in profile.items():
            setattr(config.llm.assistant_profile, key, value)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runtime_overrides.yaml"
            with patch("src.config.overrides.RUNTIME_OVERRIDES_FILE", path):
                persist_runtime_overrides(config)
                saved = load_runtime_overrides()
        restored = dict_to_config({"llm": saved["llm"]})
        self.assertEqual(restored.llm.assistant_profile.assistant_name, profile["assistant_name"])
        self.assertEqual(restored.llm.assistant_profile.system_prompt, profile["system_prompt"])
        self.assertEqual(restored.llm.assistant_profile.output_locale, profile["output_locale"])
        self.assertEqual(restored.llm.assistant_profile.enforce_output_locale, profile["enforce_output_locale"])
        self.assertEqual(restored.llm.assistant_profile.forbidden_self_names, profile["forbidden_self_names"])
