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
    def test_behavior_save_is_atomic_and_does_not_restart_the_model(self):
        from src.server.runtime_settings import apply_llm_behavior, SettingsError
        from src.llm.rules import default_rules, snapshot_from_config
        config = Config()
        config.llm.model = 'Qwen3.5-2B-UD-Q4_K_XL'
        previous_profile = config.llm.assistant_profile
        previous_rules = snapshot_from_config(config)
        profile = self._profile()
        rules = {**default_rules(), 'speech': '只說結論，細節放看板。'}
        with patch('src.server.runtime_settings.ensure_server') as start, patch(
            'src.server.runtime_settings.switch_llm_endpoint'
        ) as publish, patch('src.server.runtime_settings.persist_runtime_overrides', side_effect=OSError('full')):
            with self.assertRaises(SettingsError):
                apply_llm_behavior(config, profile, rules, expected_revision=1)
            self.assertEqual(config.llm.assistant_profile, previous_profile)
            self.assertEqual(snapshot_from_config(config), previous_rules)
            start.assert_not_called()
            publish.assert_not_called()
        with patch('src.server.runtime_settings.ensure_server') as start, patch(
            'src.server.runtime_settings.switch_llm_endpoint'
        ) as publish, patch('src.server.runtime_settings.persist_runtime_overrides') as save:
            result = apply_llm_behavior(config, profile, rules, expected_revision=1)
            self.assertEqual(result['rules']['revision'], 2)
            self.assertEqual(result['assistant_profile']['system_prompt'], profile['system_prompt'])
            self.assertEqual(config.llm.model, 'Qwen3.5-2B-UD-Q4_K_XL')
            self.assertTrue(result['history_reset'])
            save.assert_called_once()
            start.assert_not_called()
            self.assertEqual(publish.call_args.kwargs['reset_history'], True)

    def test_model_switch_preserves_saved_role_and_rules(self):
        from src.llm.rules import snapshot_from_config
        config = Config()
        config.llm.assistant_profile.system_prompt = '維持相同角色。'
        config.llm.reply_rules.activation = '只有要求看板才開啟。'
        before = snapshot_from_config(config)
        with patch('src.server.runtime_settings.ensure_server', return_value='http://localhost:8080/v1'), patch(
            'src.server.runtime_settings.switch_llm_endpoint'
        ), patch('src.server.runtime_settings.persist_runtime_overrides'):
            result = apply_llm_model(config, 'another-model', 'llamacpp')
        self.assertEqual(result['system_prompt'], '維持相同角色。')
        self.assertEqual(snapshot_from_config(config), before)
        self.assertFalse(result['history_reset'])

    def test_model_loading_does_not_overwrite_a_newly_saved_persona(self):
        from src.server.runtime_settings import apply_llm_behavior
        from src.llm.rules import default_rules
        config = Config()
        config.llm.assistant_profile.system_prompt = '原先角色。'
        def load_model(*args, **kwargs):
            apply_llm_behavior(config, self._profile(), default_rules(), expected_revision=1)
            return 'http://localhost:8080/v1'
        with patch('src.server.runtime_settings.ensure_server', side_effect=load_model), patch(
            'src.server.runtime_settings.switch_llm_endpoint'
        ), patch('src.server.runtime_settings.persist_runtime_overrides'):
            result = apply_llm_model(config, 'another-model', 'llamacpp')
        self.assertEqual(result['system_prompt'], self._profile()['system_prompt'])
        self.assertEqual(config.llm.assistant_profile.assistant_name, self._profile()['assistant_name'])
        self.assertFalse(result['history_reset'])

    def test_registered_behavior_route_persists_both_fields_and_rejects_stale_saves(self):
        import asyncio
        from aiohttp.test_utils import TestClient, TestServer
        from src.server.server import create_app
        from src.server.state import state
        from src.llm.rules import default_rules

        async def run():
            config = Config()
            rules = {**default_rules(), 'speech': '只說結論。'}
            with tempfile.TemporaryDirectory() as tmp, patch.object(state, 'config', config), patch(
                'src.config.overrides.RUNTIME_OVERRIDES_FILE', Path(tmp) / 'runtime_overrides.yaml'
            ), patch('src.server.runtime_settings.switch_llm_endpoint') as publish:
                app = create_app()
                app.on_shutdown.clear()
                async with TestClient(TestServer(app)) as client:
                    payload = {'assistant_profile': self._profile(), 'rules': rules, 'expected_revision': 1}
                    response = await client.put('/api/llm/behavior', json=payload)
                    self.assertEqual(response.status, 200)
                    saved = dict_to_config(load_runtime_overrides())
                    self.assertEqual(saved.llm.assistant_profile.system_prompt, self._profile()['system_prompt'])
                    self.assertEqual(saved.llm.reply_rules.speech, rules['speech'])
                    response = await client.put('/api/llm/behavior', json={**payload, 'assistant_profile': self._profile('other')})
                    self.assertEqual(response.status, 409)
                    self.assertEqual(config.llm.assistant_profile.assistant_name, self._profile()['assistant_name'])
                    publish.assert_called_once()

        asyncio.run(run())

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
