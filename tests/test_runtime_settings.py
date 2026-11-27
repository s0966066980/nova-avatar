# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.avatars.builder import slugify_name, suggest_avatar_id
from src.llm.llamacpp import list_gguf_models, resolve_gguf
from src.avatars.catalog import (
    avatar_bootable,
    detect_avatar_type,
    find_preview_image,
    is_safe_avatar_id,
    list_avatar_characters,
    list_engines,
)
from src.avatars.adapter import create_avatar_service
from src.config.overrides import load_runtime_overrides, persist_runtime_overrides
from src.llm.base import with_response_length_instruction
from src.server.runtime_settings import (
    MAX_STAGE_CAPTION_MAX_CHARS,
    MIN_STAGE_CAPTION_MAX_CHARS,
    SettingsError,
    apply_stage_settings,
    _is_embedding_model,
    apply_llm_model,
    apply_avatar,
    current_snapshot,
    format_bytes,
    ollama_native_url,
    apply_stt_settings,
    apply_tts_settings,
    speech_snapshot,
    stage_snapshot,
)
from src.config.schema import Config
from tests.llm_fakes import FakeLlm
from tests.tts_fakes import in_process_tts


class AvatarCatalogTests(unittest.TestCase):
    def test_safe_avatar_id(self):
        self.assertTrue(is_safe_avatar_id("musetalk_avatar1"))
        self.assertTrue(is_safe_avatar_id("musetalk-avatar.2"))
        self.assertFalse(is_safe_avatar_id("../etc/passwd"))
        self.assertFalse(is_safe_avatar_id("a/b"))
        self.assertFalse(is_safe_avatar_id(""))

    def test_detect_musetalk_and_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            muse = root / "muse_role"
            (muse / "mask").mkdir(parents=True)
            (muse / "latents.pt").write_bytes(b"x")
            # An avatar made for the removed Wav2Lip engine is not recognised.
            wav = root / "wav_role"
            (wav / "face_imgs").mkdir(parents=True)
            (wav / "coords.pkl").write_bytes(b"x")
            unknown = root / "notes"
            unknown.mkdir()
            (unknown / "readme.txt").write_text("nope")

            self.assertEqual(detect_avatar_type(muse), "musetalk")
            self.assertIsNone(detect_avatar_type(wav))
            self.assertIsNone(detect_avatar_type(unknown))

    def test_preview_prefers_numbered_full_imgs(self):
        with tempfile.TemporaryDirectory() as tmp:
            avatar = Path(tmp)
            imgs = avatar / "full_imgs"
            imgs.mkdir()
            (imgs / "00000010.png").write_bytes(b"10")
            (imgs / "00000002.png").write_bytes(b"02")
            preview = find_preview_image(avatar)
            self.assertEqual(preview.name, "00000002.png")

    def test_list_characters_and_engines(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            avatar_root = data_dir / "avatars"
            muse = avatar_root / "musetalk_avatar1"
            (muse / "full_imgs").mkdir(parents=True)
            (muse / "mask").mkdir()
            (muse / "latents.pt").write_bytes(b"x")
            (muse / "full_imgs" / "00000000.png").write_bytes(b"img")
            (muse / "avator_info.json").write_text(
                '{"avatar_id": "musetalk_avatar1"}', encoding="utf-8"
            )

            models_dir = data_dir / "models"
            (models_dir / "musetalk" / "musetalkV15").mkdir(parents=True)
            (models_dir / "musetalk" / "musetalkV15" / "unet.pth").write_bytes(b"w")

            with patch("src.avatars.catalog.get_data_dir", return_value=data_dir), patch(
                "src.avatars.catalog.get_models_dir", return_value=models_dir
            ):
                characters = list_avatar_characters()
                engines = {item["id"]: item for item in list_engines(characters)}
                ok, reason = avatar_bootable("musetalk", "musetalk_avatar1")
                missing_ok, missing_reason = avatar_bootable("musetalk", "missing")

            self.assertEqual(len(characters), 1)
            self.assertEqual(characters[0]["type"], "musetalk")
            self.assertTrue(characters[0]["has_preview"])
            self.assertTrue(engines["musetalk"]["available"])
            self.assertTrue(engines["musetalk"]["can_import"])
            self.assertEqual(set(engines), {"musetalk"})
            self.assertTrue(ok, reason)
            self.assertFalse(missing_ok)
            self.assertIn("找不到角色", missing_reason)


class OllamaHelperTests(unittest.TestCase):
    def test_native_url_strips_v1(self):
        self.assertEqual(
            ollama_native_url("http://localhost:11434/v1"),
            "http://localhost:11434",
        )
        self.assertEqual(
            ollama_native_url("http://127.0.0.1:11434/v1/"),
            "http://127.0.0.1:11434",
        )

    def test_format_bytes(self):
        self.assertEqual(format_bytes(0), "")
        self.assertEqual(format_bytes(512), "512 B")
        self.assertEqual(format_bytes(2 * 1024 ** 3), "2.0 GB")

    def test_skip_embedding_models(self):
        self.assertTrue(_is_embedding_model("nomic-embed-text:latest", "nomic-bert"))
        self.assertFalse(_is_embedding_model("qwen3.5:4b", "qwen35"))


class OverridePersistTests(unittest.TestCase):
    def test_failed_replace_preserves_previous_settings_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runtime_overrides.yaml"
            previous = "previous: settings\n"
            path.write_text(previous, encoding="utf-8")

            with (
                patch("src.config.overrides.RUNTIME_OVERRIDES_FILE", path),
                patch(
                    "src.config.overrides.os.replace",
                    side_effect=OSError("simulated replace failure"),
                ),
                self.assertRaisesRegex(OSError, "simulated replace failure"),
            ):
                persist_runtime_overrides(Config())

            self.assertEqual(path.read_text(encoding="utf-8"), previous)
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runtime_overrides.yaml"

            class LLM:
                model = "qwen3.5:4b"
                max_tokens = 360
                response_max_chars = 240
                system_prompt = "請用繁體中文簡短回答。"

            class Model:
                type = "musetalk"
                avatar_id = "musetalk_avatar1"

            class Config:
                llm = LLM()
                model = Model()
                reply_streaming = SimpleNamespace(enabled=True)

            with patch("src.config.overrides.RUNTIME_OVERRIDES_FILE", path):
                persist_runtime_overrides(Config())
                data = load_runtime_overrides()

            self.assertEqual(data["llm"]["model"], "qwen3.5:4b")
            self.assertEqual(data["llm"]["max_tokens"], 360)
            self.assertEqual(data["llm"]["response_max_chars"], 240)
            self.assertEqual(data["llm"]["assistant_profile"]["system_prompt"], "")
            self.assertEqual(data["model"]["type"], "musetalk")
            self.assertEqual(data["model"]["avatar_id"], "musetalk_avatar1")
            self.assertIs(data["reply_streaming"]["enabled"], True)

    def test_a_config_without_stage_settings_saves_the_stage_schema_defaults(self):
        """The writer's fallbacks for a missing stage section must not drift from StageConfig."""
        from src.config.schema import StageConfig

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runtime_overrides.yaml"

            def saved_stage(**extra):
                config = SimpleNamespace(
                    llm=SimpleNamespace(model="m", system_prompt=""),
                    model=SimpleNamespace(type="musetalk", avatar_id="a"),
                    **extra,
                )
                with patch("src.config.overrides.RUNTIME_OVERRIDES_FILE", path):
                    persist_runtime_overrides(config)
                    return load_runtime_overrides()["stage"]

            self.assertEqual(saved_stage(), saved_stage(stage=StageConfig()))


class DefaultPromptSettingsTests(unittest.TestCase):
    def test_snapshot_exposes_user_selectable_reply_mode(self):
        config = Config()
        config.reply_streaming.enabled = True
        with patch(
            "src.avatars.catalog.list_avatar_characters", return_value=[]
        ), patch("src.avatars.catalog.list_engines", return_value=[]):
            snapshot = current_snapshot(config, tts=in_process_tts(), avatars=create_avatar_service())

        self.assertEqual(snapshot["llm"]["reply_mode"], "streaming")

    def test_apply_llm_updates_and_persists_reply_mode(self):
        config = Config()
        config.llm.provider = "ollama"
        config.llm.base_url = "http://localhost:11434/v1"

        llm = FakeLlm()
        with patch("src.server.runtime_settings.persist_runtime_overrides") as persist:
            result = apply_llm_model(
                config,
                "qwen3.5:4b",
                "ollama",
                "請使用繁體中文回答。",
                120,
                "legacy",
                llm=llm,
            )

        self.assertFalse(config.reply_streaming.enabled)
        self.assertEqual(result["reply_mode"], "legacy")
        persist.assert_called_once_with(config)

    def test_snapshot_exposes_effective_default_prompt(self):
        config = Config()
        config.llm.system_prompt = ""
        with patch(
            "src.avatars.catalog.list_avatar_characters", return_value=[]
        ), patch("src.avatars.catalog.list_engines", return_value=[]):
            snapshot = current_snapshot(config, tts=in_process_tts(), avatars=create_avatar_service())

        self.assertEqual(snapshot["llm"]["system_prompt"], "You are a helpful assistant.")

    def test_apply_llm_persists_and_updates_prompt(self):
        config = Config()
        config.llm.provider = "ollama"
        config.llm.base_url = "http://localhost:11434/v1"
        prompt = "你是數位人助理，請使用繁體中文簡短回答。"

        llm = FakeLlm()
        with patch("src.server.runtime_settings.persist_runtime_overrides") as persist:
            result = apply_llm_model(config, "qwen3.5:4b", "ollama", prompt, llm=llm)

        self.assertEqual(config.llm.assistant_profile.system_prompt, prompt)
        self.assertEqual(config.llm.system_prompt, "")
        self.assertEqual(result["system_prompt"], prompt)
        persist.assert_called_once_with(config)
        self.assertEqual(llm.engine_settings[-1].system_prompt, prompt)

    def test_apply_llm_rejects_empty_prompt(self):
        llm = FakeLlm()
        with self.assertRaises(SettingsError):
            apply_llm_model(Config(), "qwen3.5:4b", "ollama", "   ", llm=llm)

    def test_snapshot_exposes_response_length(self):
        config = Config()
        config.llm.response_max_chars = 240
        with patch(
            "src.avatars.catalog.list_avatar_characters", return_value=[]
        ), patch("src.avatars.catalog.list_engines", return_value=[]):
            snapshot = current_snapshot(config, tts=in_process_tts(), avatars=create_avatar_service())

        self.assertEqual(snapshot["llm"]["response_max_chars"], 240)

    def test_snapshot_exposes_board_item_limit(self):
        config = Config()
        config.llm.board.max_items = 6
        with patch(
            "src.avatars.catalog.list_avatar_characters", return_value=[]
        ), patch("src.avatars.catalog.list_engines", return_value=[]):
            snapshot = current_snapshot(config, tts=in_process_tts(), avatars=create_avatar_service())

        self.assertEqual(snapshot["llm"]["board_max_items"], 6)

    def test_snapshot_exposes_stage_caption_limit(self):
        config = Config()
        config.stage.caption_max_chars = 240
        with patch(
            "src.avatars.catalog.list_avatar_characters", return_value=[]
        ), patch("src.avatars.catalog.list_engines", return_value=[]):
            snapshot = current_snapshot(config, tts=in_process_tts(), avatars=create_avatar_service())

        self.assertEqual(snapshot["stage"]["caption_max_chars"], 240)
        self.assertEqual(snapshot["stage"]["board_style"], "glass")

    def test_apply_stage_settings_updates_and_persists(self):
        config = Config()

        with patch("src.server.runtime_settings.persist_runtime_overrides") as persist:
            result = apply_stage_settings(config, {"caption_max_chars": 360})

        self.assertEqual(config.stage.caption_max_chars, 360)
        self.assertEqual(result["caption_max_chars"], 360)
        self.assertEqual(result["board_style"], "glass")
        persist.assert_called_once_with(config)

    def test_apply_stage_settings_updates_board_window(self):
        config = Config()

        with patch("src.server.runtime_settings.persist_runtime_overrides") as persist:
            result = apply_stage_settings(
                config,
                {
                    "caption_x": 35,
                    "caption_y": 74,
                    "caption_width": 68,
                    "board_style": "slate",
                    "board_width": 280,
                    "board_height": 360,
                    "board_transparency": 40,
                    "board_x": 0,
                    "board_y": 0,
                    "board_preset": "tl",
                    "board_preview": False,
                    "board_open_x": 24,
                    "board_open_y": 76,
                },
            )

        self.assertEqual(config.stage.board_style, "slate")
        self.assertEqual(config.stage.caption_x, 35)
        self.assertEqual(config.stage.caption_y, 74)
        self.assertEqual(config.stage.caption_width, 68)
        self.assertEqual(config.stage.board_width, 280)
        self.assertEqual(config.stage.board_preset, "tl")
        self.assertFalse(config.stage.board_preview)
        self.assertEqual(config.stage.board_open_x, 24)
        self.assertEqual(config.stage.board_open_y, 76)
        self.assertEqual(result["board_open_x"], 24)
        self.assertEqual(result["board_open_y"], 76)
        self.assertEqual(result["board_style"], "slate")
        persist.assert_called_once_with(config)

    def test_apply_stage_settings_rejects_invalid_values(self):
        for value in (
            MIN_STAGE_CAPTION_MAX_CHARS - 1,
            MAX_STAGE_CAPTION_MAX_CHARS + 1,
            120.5,
            True,
            "not-a-number",
        ):
            with self.subTest(value=value), self.assertRaises(SettingsError):
                apply_stage_settings(Config(), {"caption_max_chars": value})

        with self.assertRaises(SettingsError):
            apply_stage_settings(Config(), {"board_style": "neon"})
        with self.assertRaises(SettingsError):
            apply_stage_settings(Config(), {"board_width": 80})
        with self.assertRaises(SettingsError):
            apply_stage_settings(Config(), {"caption_width": 39})

    def test_idle_reset_seconds_defaults_to_sixty_and_persists_when_changed(self):
        config = Config()
        self.assertEqual(stage_snapshot(config)["idle_reset_seconds"], 60)

        with patch("src.server.runtime_settings.persist_runtime_overrides") as persist:
            result = apply_stage_settings(config, {"idle_reset_seconds": 45})

        self.assertEqual(config.stage.idle_reset_seconds, 45)
        self.assertEqual(result["idle_reset_seconds"], 45)
        persist.assert_called_once_with(config)

    def test_idle_reset_seconds_rejects_values_outside_three_to_three_hundred(self):
        for value in (2, 301, 10.5, True, "not-a-number"):
            with self.subTest(value=value), self.assertRaises(SettingsError):
                apply_stage_settings(Config(), {"idle_reset_seconds": value})

    def test_stage_snapshot_rejects_invalid_config_value(self):
        config = Config()
        config.stage.caption_max_chars = 19
        with self.assertRaises(ValueError):
            stage_snapshot(config)

    def test_apply_llm_updates_response_length_and_token_budget(self):
        config = Config()
        config.llm.provider = "ollama"
        config.llm.base_url = "http://localhost:11434/v1"

        llm = FakeLlm()
        with patch("src.server.runtime_settings.persist_runtime_overrides"):
            result = apply_llm_model(
                config,
                "qwen3.5:4b",
                "ollama",
                "請使用繁體中文回答。",
                240,
                llm=llm,
            )

        self.assertEqual(config.llm.response_max_chars, 240)
        self.assertEqual(config.llm.max_tokens, 888)
        self.assertEqual(result["response_max_chars"], 240)
        self.assertEqual(llm.engine_settings[-1].response_max_chars, 240)
        self.assertEqual(llm.engine_settings[-1].max_tokens, 888)
        self.assertEqual(config.llm.extra_body["options"]["num_predict"], 888)

    def test_apply_llm_rejects_invalid_response_length(self):
        llm = FakeLlm()
        with self.assertRaises(SettingsError):
            apply_llm_model(
                Config(),
                "qwen3.5:4b",
                "ollama",
                "請使用繁體中文回答。",
                19,
                llm=llm,
            )

    def test_apply_llm_updates_and_validates_board_item_limit(self):
        config = Config()
        config.llm.provider = "ollama"
        config.llm.base_url = "http://localhost:11434/v1"

        llm = FakeLlm()
        with patch("src.server.runtime_settings.persist_runtime_overrides"):
            result = apply_llm_model(
                config,
                "qwen3.5:4b",
                "ollama",
                "請使用繁體中文回答。",
                board_max_items=6,
                llm=llm,
            )

        self.assertEqual(config.llm.board.max_items, 6)
        self.assertEqual(result["board_max_items"], 6)

        llm = FakeLlm()
        for value in (0, 13, 2.5, True, "invalid"):
            with self.subTest(value=value), self.assertRaises(SettingsError):
                apply_llm_model(
                    Config(),
                    "qwen3.5:4b",
                    "ollama",
                    "請使用繁體中文回答。",
                    board_max_items=value,
                    llm=llm,
                )

    def test_length_instruction_preserves_prompt_and_requests_complete_sentence(self):
        prompt = with_response_length_instruction("請使用繁體中文回答。", 120)
        self.assertTrue(prompt.startswith("請使用繁體中文回答。"))
        self.assertIn("總長度約 120 個字", prompt)
        self.assertIn("禁止在句子或條目中途停止", prompt)

    def test_token_budget_is_a_ceiling_above_the_character_target(self):
        from src.llm.base import response_token_budget

        self.assertGreaterEqual(response_token_budget(200), 500)
        self.assertGreater(response_token_budget(200), 200 * 1.5)


class ApplyAvatarGuardTests(unittest.TestCase):
    def test_requires_disconnect_when_session_active(self):
        class LLM:
            model = "qwen3.5:4b"

        class Model:
            type = "musetalk"
            avatar_id = "musetalk_avatar1"

        class Config:
            llm = LLM()
            model = Model()

        characters = [
            {"id": "musetalk_avatar1", "type": "musetalk"},
            {"id": "musetalk_avatar2", "type": "musetalk"},
        ]
        engines = [
            {
                "id": "musetalk",
                "available": True,
                "message": "",
            }
        ]
        with patch(
            "src.avatars.catalog.list_avatar_characters",
            return_value=characters,
        ), patch(
            "src.avatars.catalog.list_engines",
            return_value=engines,
        ):
            with self.assertRaises(SettingsError) as ctx:
                apply_avatar(Config(), "musetalk", "musetalk_avatar2", session_count=1, avatars=create_avatar_service())
        self.assertEqual(ctx.exception.status, 409)
        self.assertTrue(ctx.exception.extra.get("need_disconnect"))

    def test_rejects_unknown_engine(self):
        class Model:
            type = "musetalk"
            avatar_id = "musetalk_avatar1"

        class Config:
            model = Model()

        with self.assertRaises(SettingsError):
            apply_avatar(Config(), "not-a-real-engine", "x", session_count=0, avatars=create_avatar_service())


class SpeechSettingsTests(unittest.TestCase):
    def test_catalog_contains_only_keyless_tts(self):
        ids = {item["id"] for item in speech_snapshot(Config(), tts=in_process_tts())["tts"]["engines"]}
        self.assertEqual(
            ids,
            {"edgetts", "breezyvoice", "matcha"},
        )
        self.assertTrue(ids.isdisjoint({"azuretts", "cosyvoice_api", "doubao", "tencent"}))

    def test_snapshot_lists_all_edge_tts_zh_tw_voices(self):
        voices = speech_snapshot(Config(), tts=in_process_tts())["tts"]["edge_voices"]
        self.assertEqual(
            {voice["id"] for voice in voices},
            {
                "zh-TW-HsiaoChenNeural",
                "zh-TW-HsiaoYuNeural",
                "zh-TW-YunJheNeural",
            },
        )
        self.assertEqual(
            {voice["gender"] for voice in voices},
            {"female", "male"},
        )

    def test_snapshot_exposes_the_conversation_english_voice_catalog(self):
        from src.server.conversations import VOICES

        voices = speech_snapshot(Config(), tts=in_process_tts())["tts"]["edge_english_voices"]
        self.assertEqual(voices, VOICES["en-US"])

    def test_stt_engines_describe_their_models(self):
        # The console renders the speech-recognition form from these entries.
        engines = {item["id"]: item for item in speech_snapshot(Config(), tts=in_process_tts())["stt"]["engines"]}
        self.assertEqual(set(engines), {"whisper"})
        self.assertEqual(engines["whisper"]["models"], ["tiny", "base", "small", "medium", "large-v3", "turbo"])

    def test_tts_snapshot_has_no_global_voice(self):
        # The default voice is the main role profile's, edited there.
        tts = speech_snapshot(Config(), tts=in_process_tts())["tts"]
        self.assertFalse({"type", "ref_file", "ref_text", "tts_server", "model"} & set(tts))

    def test_tts_rejects_removed_provider(self):
        with self.assertRaises(SettingsError):
            apply_tts_settings(Config(), {"type": "azuretts"}, session_count=0, tts=in_process_tts())

    def _library_voice(self) -> str:
        """A voice in a temporary voice library; returns its ID."""
        import numpy as np
        import soundfile as sf
        from src.tts import voice_library

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        tmp = Path(directory.name)
        patcher = patch.object(voice_library, "VOICES_ROOT", tmp / "voices")
        patcher.start()
        self.addCleanup(patcher.stop)
        source = tmp / "reference.wav"
        sf.write(source, np.full(16000, 0.1, dtype=np.float32), 16000)
        return voice_library.add_voice(source, "reference")["id"]

    def test_speech_engine_change_requires_disconnect(self):
        with self.assertRaises(SettingsError) as ctx:
            apply_stt_settings(Config(), {"type": "whisper"}, session_count=1, stt=Mock())
        self.assertEqual(ctx.exception.status, 409)
        self.assertTrue(ctx.exception.extra["need_disconnect"])

    def test_breezyvoice_missing_reference_does_not_silently_fall_back(self):
        with patch("src.server.runtime_settings._engine_available", return_value=True):
            with self.assertRaises(SettingsError) as ctx:
                apply_tts_settings(
                    Config(),
                    {"type": "breezyvoice", "ref_file": "0123456789abcdef"},
                    session_count=0, tts=in_process_tts(),
                )
        self.assertIn("不在音訊庫中", ctx.exception.message)

    def test_tts_commits_only_after_preview(self):
        config = Config()
        with patch("src.server.runtime_settings._engine_available", return_value=True), patch(
            "src.server.runtime_settings._preview_tts",
            return_value="data:audio/wav;base64,dGVzdA==",
        ), patch("src.server.runtime_settings.persist_runtime_overrides") as persist:
            result = apply_tts_settings(
                config,
                {"type": "edgetts", "ref_file": "zh-TW-HsiaoChenNeural"},
                session_count=0, tts=in_process_tts(),
            )
        self.assertEqual(config.tts.type, "edgetts")
        self.assertIn("preview_audio", result)
        persist.assert_called_once()

    def test_edge_tts_rejects_non_zh_tw_voice(self):
        with patch("src.server.runtime_settings._engine_available", return_value=True):
            with self.assertRaises(SettingsError) as ctx:
                apply_tts_settings(
                    Config(),
                    {"type": "edgetts", "ref_file": "zh-CN-XiaoxiaoNeural"},
                    session_count=0, tts=in_process_tts(),
                )
        self.assertIn("台灣華語聲線", ctx.exception.message)

    def test_stt_service_loads_the_engine_before_commit(self):
        from nova_contracts.stt import SttEngineSettings

        config = Config()
        stt = Mock()
        with patch("src.server.runtime_settings._engine_available", return_value=True), patch(
            "src.server.runtime_settings.persist_runtime_overrides"
        ) as persist:
            result = apply_stt_settings(
                config,
                {
                    "type": "whisper",
                    "model_size": "small",
                    "language": "auto",
                    "device": "cuda",
                },
                session_count=0,
                stt=stt,
            )
        stt.apply_engine.assert_called_once_with(
            SttEngineSettings(engine="whisper", model_size="small", device="cuda"))
        self.assertEqual(result["model_size"], "small")
        self.assertEqual((config.asr.device, config.asr.language), ("cuda", "auto"))
        persist.assert_called_once()

    def test_stt_engine_the_service_cannot_load_is_not_committed(self):
        from nova_contracts.common import ServiceError

        config = Config()
        stt = Mock()
        stt.apply_engine.side_effect = ServiceError("CUDA out of memory")
        with patch("src.server.runtime_settings._engine_available", return_value=True), patch(
            "src.server.runtime_settings.persist_runtime_overrides"
        ) as persist, self.assertRaises(SettingsError) as ctx:
            apply_stt_settings(
                config, {"type": "whisper", "model_size": "turbo", "device": "cuda"},
                session_count=0, stt=stt,
            )
        self.assertEqual(ctx.exception.status, 500)
        self.assertIn("CUDA out of memory", ctx.exception.message)
        self.assertNotEqual(config.asr.model_size, "turbo")
        persist.assert_not_called()

    def test_removed_funasr_engine_is_rejected(self):
        with self.assertRaises(SettingsError):
            apply_stt_settings(
                Config(),
                {"type": "funasr", "model_size": "Fun-ASR-Nano-2512"},
                session_count=0,
                stt=Mock(),
            )

    def test_saved_funasr_settings_load_as_faster_whisper(self):
        from src.config.loader import dict_to_config

        config = dict_to_config({"asr": {
            "type": "funasr",
            "model_size": "Fun-ASR-Nano-2512",
            "language": "auto",
            "output_script": "simplified",
        }})
        self.assertEqual(config.asr.type, "whisper")
        self.assertEqual(config.asr.model_size, "small")
        self.assertEqual(config.asr.language, "auto")
        self.assertFalse(hasattr(config.asr, "output_script"))

    def test_removed_qwen_speech_engines_are_rejected(self):
        with self.assertRaises(SettingsError):
            apply_stt_settings(
                Config(),
                {"type": "qwen3-asr", "model_size": "Qwen/Qwen3-ASR-0.6B"},
                session_count=0,
                stt=Mock(),
            )
        with self.assertRaises(SettingsError):
            apply_tts_settings(
                Config(),
                {"type": "qwen3-tts", "model": "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"},
                session_count=0, tts=in_process_tts(),
            )
        snapshot = speech_snapshot(Config(), tts=in_process_tts())
        self.assertNotIn("qwen3-asr", snapshot["stt"]["models_by_engine"])
        self.assertNotIn(
            "qwen3-tts",
            {item["id"] for item in snapshot["tts"]["engines"]},
        )


class AvatarNameTests(unittest.TestCase):
    def test_slugify_and_suggest(self):
        self.assertEqual(slugify_name("My Video.mp4"), "my_video")
        self.assertEqual(slugify_name("../weird name!!.MOV"), "weird_name")
        existing = {"musetalk_jonghyun"}
        self.assertEqual(
            suggest_avatar_id("musetalk", "jonghyun.mp4", existing),
            "musetalk_jonghyun_2",
        )
        self.assertEqual(
            suggest_avatar_id("musetalk", "silent.mp4", set()),
            "musetalk_silent",
        )


class LlamaCppCatalogTests(unittest.TestCase):
    def test_lists_and_resolves_gguf(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            gguf = folder / "fixture-model.gguf"
            gguf.write_bytes(b"fake")
            models = list_gguf_models(str(folder))
            names = [item["name"] for item in models]
            self.assertIn("fixture-model", names)
            self.assertEqual(resolve_gguf("fixture-model", str(folder)), gguf)

    def test_failed_reload_does_not_mutate_config(self):
        class LLM:
            def __init__(self):
                self.model = "qwen3.5:4b"

        class Model:
            def __init__(self):
                self.type = "musetalk"
                self.avatar_id = "musetalk_avatar1"

        class Config:
            def __init__(self):
                self.llm = LLM()
                self.model = Model()

        config = Config()
        characters = [
            {"id": "musetalk_avatar1", "type": "musetalk"},
            {"id": "musetalk_avatar2", "type": "musetalk"},
        ]
        engines = [
            {"id": "musetalk", "available": True, "message": ""},
        ]

        def boom(_config):
            raise FileNotFoundError("missing weights")

        with patch(
            "src.avatars.catalog.list_avatar_characters",
            return_value=characters,
        ), patch(
            "src.avatars.catalog.list_engines",
            return_value=engines,
        ), patch(
            "src.avatars.factory.prepare_avatar_model",
            side_effect=boom,
        ), patch(
            "src.avatars.factory.load_avatar_data",
            side_effect=boom,
        ):
            with self.assertRaises(SettingsError):
                apply_avatar(config, "musetalk", "musetalk_avatar2", session_count=0, avatars=create_avatar_service())

        self.assertEqual(config.model.type, "musetalk")
        self.assertEqual(config.model.avatar_id, "musetalk_avatar1")


if __name__ == "__main__":
    unittest.main()
