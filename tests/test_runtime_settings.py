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
    resolve_wav2lip_weights,
)
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
    is_ollama_endpoint,
    ollama_native_url,
    apply_stt_settings,
    apply_tts_settings,
    speech_snapshot,
    stage_snapshot,
)
from src.config.schema import Config


class AvatarCatalogTests(unittest.TestCase):
    def test_safe_avatar_id(self):
        self.assertTrue(is_safe_avatar_id("musetalk_avatar1"))
        self.assertTrue(is_safe_avatar_id("wav2lip-avatar.2"))
        self.assertFalse(is_safe_avatar_id("../etc/passwd"))
        self.assertFalse(is_safe_avatar_id("a/b"))
        self.assertFalse(is_safe_avatar_id(""))

    def test_detect_musetalk_and_wav2lip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            muse = root / "muse_role"
            (muse / "mask").mkdir(parents=True)
            (muse / "latents.pt").write_bytes(b"x")
            wav = root / "wav_role"
            (wav / "face_imgs").mkdir(parents=True)
            (wav / "coords.pkl").write_bytes(b"x")
            unknown = root / "notes"
            unknown.mkdir()
            (unknown / "readme.txt").write_text("nope")

            self.assertEqual(detect_avatar_type(muse), "musetalk")
            self.assertEqual(detect_avatar_type(wav), "wav2lip")
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

            self.assertEqual(len(characters), 1)
            self.assertEqual(characters[0]["type"], "musetalk")
            self.assertTrue(characters[0]["has_preview"])
            self.assertTrue(engines["musetalk"]["available"])
            self.assertTrue(engines["musetalk"]["can_import"])
            self.assertFalse(engines["wav2lip"]["available"])
            self.assertTrue(engines["wav2lip"]["can_import"])
            self.assertFalse(engines["ernerf"]["can_import"])
            ok, reason = avatar_bootable("musetalk", "musetalk_avatar1")
            self.assertTrue(ok, reason)
            ok, reason = avatar_bootable("musetalk", "missing")
            self.assertFalse(ok)
            self.assertIn("找不到角色", reason)


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

    def test_detect_ollama_endpoint(self):
        self.assertTrue(is_ollama_endpoint("http://localhost:11434/v1"))
        self.assertTrue(is_ollama_endpoint("http://127.0.0.1:11434/v1"))
        self.assertFalse(is_ollama_endpoint("https://dashscope.aliyuncs.com/compatible-mode/v1"))

    def test_format_bytes(self):
        self.assertEqual(format_bytes(0), "")
        self.assertEqual(format_bytes(512), "512 B")
        self.assertEqual(format_bytes(2 * 1024 ** 3), "2.0 GB")

    def test_skip_embedding_models(self):
        self.assertTrue(_is_embedding_model("nomic-embed-text:latest", "nomic-bert"))
        self.assertFalse(_is_embedding_model("qwen3.5:4b", "qwen35"))


class Wav2LipWeightsTests(unittest.TestCase):
    def test_prefers_existing_256_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp)
            (models / "wav2lip256.pth").write_bytes(b"w")
            with patch("src.avatars.catalog.get_models_dir", return_value=models):
                path = resolve_wav2lip_weights()
            self.assertEqual(path.name, "wav2lip256.pth")

    def test_prefers_standard_name_when_both_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp)
            (models / "wav2lip.pth").write_bytes(b"a")
            (models / "wav2lip256.pth").write_bytes(b"b")
            with patch("src.avatars.catalog.get_models_dir", return_value=models):
                path = resolve_wav2lip_weights()
            self.assertEqual(path.name, "wav2lip.pth")


class OverridePersistTests(unittest.TestCase):
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
            self.assertEqual(data["llm"]["system_prompt"], "請用繁體中文簡短回答。")
            self.assertEqual(data["llm"]["board"]["max_items"], 8)
            self.assertEqual(data["model"]["type"], "musetalk")
            self.assertEqual(data["model"]["avatar_id"], "musetalk_avatar1")
            self.assertEqual(data["model"]["mouth_sharpen"], 0.5)
            self.assertEqual(data["model"]["paste_interpolation"], "lanczos")
            self.assertEqual(data["model"]["musetalk"]["extra_margin"], 10)
            self.assertEqual(
                data["reply_streaming"],
                {
                    "enabled": True,
                    "decoupled_audio_clock": False,
                    "strong_min_chars": 1,
                },
            )
            self.assertEqual(
                data["stage"],
                {
                    "caption_max_chars": 120,
                    "caption_x": 50,
                    "caption_y": 90,
                    "caption_width": 100,
                    "board_style": "glass",
                    "board_width": 252,
                    "board_height": 300,
                    "board_transparency": 28,
                    "board_x": 100,
                    "board_y": 0,
                    "board_preset": "tr",
                    "board_preview": False,
                    "mic_x": 50,
                    "mic_y": 62,
                    "mic_preset": "custom",
                    "board_open_x": 50,
                    "board_open_y": 8,
                },
            )


class DefaultPromptSettingsTests(unittest.TestCase):
    def test_snapshot_exposes_user_selectable_reply_mode(self):
        config = Config()
        config.reply_streaming.enabled = True
        with patch(
            "src.server.runtime_settings.list_avatar_characters", return_value=[]
        ), patch("src.server.runtime_settings.list_engines", return_value=[]):
            snapshot = current_snapshot(config)

        self.assertEqual(snapshot["llm"]["reply_mode"], "streaming")

    def test_apply_llm_updates_and_persists_reply_mode(self):
        config = Config()
        config.llm.provider = "ollama"
        config.llm.base_url = "http://localhost:11434/v1"

        with patch("src.server.runtime_settings.persist_runtime_overrides") as persist, patch(
            "src.server.runtime_settings.switch_llm_endpoint"
        ):
            result = apply_llm_model(
                config,
                "qwen3.5:4b",
                "ollama",
                "請使用繁體中文回答。",
                120,
                "legacy",
            )

        self.assertFalse(config.reply_streaming.enabled)
        self.assertEqual(result["reply_mode"], "legacy")
        persist.assert_called_once_with(config)

    def test_snapshot_exposes_effective_default_prompt(self):
        config = Config()
        config.llm.system_prompt = ""
        with patch(
            "src.server.runtime_settings.list_avatar_characters", return_value=[]
        ), patch("src.server.runtime_settings.list_engines", return_value=[]):
            snapshot = current_snapshot(config)

        self.assertIn("繁體中文", snapshot["llm"]["system_prompt"])

    def test_apply_llm_persists_and_updates_prompt(self):
        config = Config()
        config.llm.provider = "ollama"
        config.llm.base_url = "http://localhost:11434/v1"
        prompt = "你是數位人助理，請使用繁體中文簡短回答。"

        with patch("src.server.runtime_settings.persist_runtime_overrides") as persist, patch(
            "src.server.runtime_settings.switch_llm_endpoint"
        ) as switch:
            result = apply_llm_model(config, "qwen3.5:4b", "ollama", prompt)

        self.assertEqual(config.llm.system_prompt, prompt)
        self.assertEqual(result["system_prompt"], prompt)
        persist.assert_called_once_with(config)
        self.assertEqual(switch.call_args.kwargs["system_prompt"], prompt)

    def test_apply_llm_rejects_empty_prompt(self):
        with self.assertRaises(SettingsError):
            apply_llm_model(Config(), "qwen3.5:4b", "ollama", "   ")

    def test_snapshot_exposes_response_length(self):
        config = Config()
        config.llm.response_max_chars = 240
        with patch(
            "src.server.runtime_settings.list_avatar_characters", return_value=[]
        ), patch("src.server.runtime_settings.list_engines", return_value=[]):
            snapshot = current_snapshot(config)

        self.assertEqual(snapshot["llm"]["response_max_chars"], 240)

    def test_snapshot_exposes_board_item_limit(self):
        config = Config()
        config.llm.board.max_items = 6
        with patch(
            "src.server.runtime_settings.list_avatar_characters", return_value=[]
        ), patch("src.server.runtime_settings.list_engines", return_value=[]):
            snapshot = current_snapshot(config)

        self.assertEqual(snapshot["llm"]["board_max_items"], 6)

    def test_snapshot_exposes_stage_caption_limit(self):
        config = Config()
        config.stage.caption_max_chars = 240
        with patch(
            "src.server.runtime_settings.list_avatar_characters", return_value=[]
        ), patch("src.server.runtime_settings.list_engines", return_value=[]):
            snapshot = current_snapshot(config)

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

    def test_stage_snapshot_rejects_invalid_config_value(self):
        config = Config()
        config.stage.caption_max_chars = 19
        with self.assertRaises(ValueError):
            stage_snapshot(config)

    def test_apply_llm_updates_response_length_and_token_budget(self):
        config = Config()
        config.llm.provider = "ollama"
        config.llm.base_url = "http://localhost:11434/v1"

        with patch("src.server.runtime_settings.persist_runtime_overrides"), patch(
            "src.server.runtime_settings.switch_llm_endpoint"
        ) as switch:
            result = apply_llm_model(
                config,
                "qwen3.5:4b",
                "ollama",
                "請使用繁體中文回答。",
                240,
            )

        self.assertEqual(config.llm.response_max_chars, 240)
        self.assertEqual(config.llm.max_tokens, 888)
        self.assertEqual(result["response_max_chars"], 240)
        self.assertEqual(switch.call_args.kwargs["response_max_chars"], 240)
        self.assertEqual(switch.call_args.kwargs["max_tokens"], 888)
        self.assertEqual(config.llm.extra_body["options"]["num_predict"], 888)

    def test_apply_llm_rejects_invalid_response_length(self):
        with self.assertRaises(SettingsError):
            apply_llm_model(
                Config(),
                "qwen3.5:4b",
                "ollama",
                "請使用繁體中文回答。",
                19,
            )

    def test_apply_llm_updates_and_validates_board_item_limit(self):
        config = Config()
        config.llm.provider = "ollama"
        config.llm.base_url = "http://localhost:11434/v1"

        with patch("src.server.runtime_settings.persist_runtime_overrides"), patch(
            "src.server.runtime_settings.switch_llm_endpoint"
        ):
            result = apply_llm_model(
                config,
                "qwen3.5:4b",
                "ollama",
                "請使用繁體中文回答。",
                board_max_items=6,
            )

        self.assertEqual(config.llm.board.max_items, 6)
        self.assertEqual(result["board_max_items"], 6)

        for value in (0, 13, 2.5, True, "invalid"):
            with self.subTest(value=value), self.assertRaises(SettingsError):
                apply_llm_model(
                    Config(),
                    "qwen3.5:4b",
                    "ollama",
                    "請使用繁體中文回答。",
                    board_max_items=value,
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
            "src.server.runtime_settings.list_avatar_characters",
            return_value=characters,
        ), patch(
            "src.server.runtime_settings.list_engines",
            return_value=engines,
        ):
            with self.assertRaises(SettingsError) as ctx:
                apply_avatar(Config(), "musetalk", "musetalk_avatar2", session_count=1)
        self.assertEqual(ctx.exception.status, 409)
        self.assertTrue(ctx.exception.extra.get("need_disconnect"))

    def test_rejects_unknown_engine(self):
        class Model:
            type = "musetalk"
            avatar_id = "musetalk_avatar1"

        class Config:
            model = Model()

        with self.assertRaises(SettingsError):
            apply_avatar(Config(), "not-a-real-engine", "x", session_count=0)


class SpeechSettingsTests(unittest.TestCase):
    def test_catalog_contains_only_keyless_tts(self):
        ids = {item["id"] for item in speech_snapshot(Config())["tts"]["engines"]}
        self.assertEqual(
            ids,
            {
                "edgetts", "gpt-sovits", "xtts",
                "cosyvoice", "fun-cosyvoice3", "fishtts", "indextts2",
            },
        )
        self.assertTrue(ids.isdisjoint({"azuretts", "cosyvoice_api", "doubao", "tencent"}))

    def test_snapshot_lists_cosyvoice_languages(self):
        languages = speech_snapshot(Config())["tts"]["languages"]
        self.assertEqual(
            [item["id"] for item in languages],
            ["zh", "en", "ja", "ko", "yue", "auto"],
        )

    def test_cosyvoice_snapshot_normalizes_language(self):
        config = Config()
        config.tts.type = "cosyvoice"
        config.tts.language = "Chinese"
        self.assertEqual(speech_snapshot(config)["tts"]["language"], "zh")

    def test_fun_cosyvoice3_snapshot_lists_extra_languages(self):
        config = Config()
        config.tts.type = "fun-cosyvoice3"
        config.tts.language = "Chinese"
        snapshot = speech_snapshot(config)["tts"]
        self.assertEqual(snapshot["language"], "zh")
        self.assertTrue(
            {"zh", "en", "de", "es", "fr", "it", "ru", "yue", "auto"}.issubset(
                {item["id"] for item in snapshot["languages"]}
            )
        )

    def test_snapshot_lists_all_edge_tts_zh_tw_voices(self):
        voices = speech_snapshot(Config())["tts"]["edge_voices"]
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

    def test_tts_rejects_removed_provider(self):
        with self.assertRaises(SettingsError):
            apply_tts_settings(Config(), {"type": "azuretts"}, session_count=0)

    def test_zero_shot_requires_reference_transcript_before_starting_server(self):
        with patch("src.server.runtime_settings._engine_available", return_value=True), patch(
            "src.tts.cosyvoice_runtime.ensure_server"
        ) as ensure:
            with self.assertRaisesRegex(SettingsError, "參考語音逐字稿"):
                apply_tts_settings(
                    Config(),
                    {
                        "type": "fun-cosyvoice3",
                        "mode": "zero_shot",
                        "ref_file": "/tmp/reference.wav",
                        "ref_text": "",
                    },
                    session_count=0,
                )
        ensure.assert_not_called()

    def test_speech_engine_change_requires_disconnect(self):
        with self.assertRaises(SettingsError) as ctx:
            apply_stt_settings(Config(), {"type": "whisper"}, session_count=1)
        self.assertEqual(ctx.exception.status, 409)
        self.assertTrue(ctx.exception.extra["need_disconnect"])

    def test_cosyvoice_auto_starts_local_server_and_uses_default_prompt(self):
        config = Config()
        with tempfile.TemporaryDirectory() as tmp:
            default_wav = Path(tmp) / "cosyvoice_prompt.wav"
            default_wav.write_bytes(b"RIFF")
            with patch("src.server.runtime_settings._engine_available", return_value=True), patch(
                "src.tts.cosyvoice_runtime.ensure_server",
                return_value="http://127.0.0.1:50000",
            ) as ensure, patch(
                "src.tts.cosyvoice_runtime.DEFAULT_PROMPT_WAV",
                default_wav,
            ), patch(
                "src.server.runtime_settings._preview_tts",
                return_value="data:audio/wav;base64,dGVzdA==",
            ), patch("src.server.runtime_settings.persist_runtime_overrides"):
                result = apply_tts_settings(
                    config,
                    {"type": "cosyvoice"},
                    session_count=0,
                )
        self.assertEqual(config.tts.type, "cosyvoice")
        self.assertEqual(config.tts.tts_server, "http://127.0.0.1:50000")
        self.assertTrue(config.tts.ref_file.endswith("cosyvoice_prompt.wav"))
        self.assertEqual(config.tts.ref_text, "你好，我是數字人助手。")
        ensure.assert_called_once()
        self.assertIn("preview_audio", result)
        self.assertEqual(config.tts.language, "zh")
        self.assertEqual(
            {item["id"] for item in result["languages"]},
            {"zh", "en", "ja", "ko", "yue", "auto"},
        )

    def test_cosyvoice_converts_mp3_reference_instead_of_rejecting_it(self):
        from src.tts.cosyvoice_runtime import prepare_prompt_wav

        mp3 = Path("/home/oliver/CosyVoice/asset/SHINeeJonghyun.mp3")
        if not mp3.is_file():
            self.skipTest("SHINeeJonghyun.mp3 is not on this machine")
        config = Config()
        with patch("src.server.runtime_settings._engine_available", return_value=True), patch(
            "src.tts.cosyvoice_runtime.ensure_server",
            return_value="http://127.0.0.1:50000",
        ), patch(
            "src.server.runtime_settings._preview_tts",
            return_value="data:audio/wav;base64,dGVzdA==",
        ), patch("src.server.runtime_settings.persist_runtime_overrides"):
            apply_tts_settings(
                config,
                {
                    "type": "cosyvoice",
                    "ref_file": str(mp3),
                    "ref_text": "test lyrics",
                },
                session_count=0,
            )
        self.assertTrue(config.tts.ref_file.endswith(".cosy24k.v2.wav"))
        self.assertTrue(Path(config.tts.ref_file).is_file())
        self.assertEqual(config.tts.ref_text, "test lyrics")
        self.assertEqual(
            Path(config.tts.ref_file).resolve(),
            prepare_prompt_wav(mp3).resolve(),
        )

    def test_fun_cosyvoice3_auto_starts_local_server(self):
        config = Config()
        with tempfile.TemporaryDirectory() as tmp:
            default_wav = Path(tmp) / "cosyvoice_prompt.wav"
            default_wav.write_bytes(b"RIFF")
            with patch("src.server.runtime_settings._engine_available", return_value=True), patch(
                "src.tts.cosyvoice_runtime.ensure_server",
                return_value="http://127.0.0.1:50000",
            ) as ensure, patch(
                "src.tts.cosyvoice_runtime.DEFAULT_PROMPT_WAV",
                default_wav,
            ), patch(
                "src.server.runtime_settings._preview_tts",
                return_value="data:audio/wav;base64,dGVzdA==",
            ), patch("src.server.runtime_settings.persist_runtime_overrides"):
                result = apply_tts_settings(
                    config,
                    {"type": "fun-cosyvoice3", "language": "zh"},
                    session_count=0,
                )
        self.assertEqual(config.tts.type, "fun-cosyvoice3")
        self.assertEqual(config.tts.language, "zh")
        self.assertEqual(config.tts.tts_server, "http://127.0.0.1:50000")
        ensure.assert_called_once()
        self.assertEqual(ensure.call_args.kwargs.get("family"), "cosyvoice3")
        self.assertIn("preview_audio", result)

    def test_fun_cosyvoice3_missing_model_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            default_wav = Path(tmp) / "cosyvoice_prompt.wav"
            default_wav.write_bytes(b"RIFF")
            with patch("src.server.runtime_settings._engine_available", return_value=True), patch(
                "src.tts.cosyvoice_runtime.DEFAULT_PROMPT_WAV",
                default_wav,
            ), patch(
                "src.tts.cosyvoice_runtime.DEFAULT_COSYVOICE3_MODEL_DIRS",
                (Path(tmp) / "missing-fun-cosyvoice3",),
            ):
                with self.assertRaises(SettingsError) as ctx:
                    apply_tts_settings(
                        Config(),
                        {"type": "fun-cosyvoice3"},
                        session_count=0,
                    )
        self.assertIn("Fun-CosyVoice 3.0", ctx.exception.message)

    def test_cosyvoice_missing_reference_does_not_silently_fall_back(self):
        with patch("src.server.runtime_settings._engine_available", return_value=True):
            with self.assertRaises(SettingsError) as ctx:
                apply_tts_settings(
                    Config(),
                    {"type": "cosyvoice", "ref_file": "/tmp/not-a-real-voice.mp3"},
                    session_count=0,
                )
        self.assertIn("不存在", ctx.exception.message)

    def test_tts_commits_only_after_preview(self):
        config = Config()
        with patch("src.server.runtime_settings._engine_available", return_value=True), patch(
            "src.server.runtime_settings._preview_tts",
            return_value="data:audio/wav;base64,dGVzdA==",
        ), patch("src.server.runtime_settings.persist_runtime_overrides") as persist:
            result = apply_tts_settings(
                config,
                {"type": "edgetts", "ref_file": "zh-TW-HsiaoChenNeural"},
                session_count=0,
            )
        self.assertEqual(config.tts.type, "edgetts")
        self.assertIn("preview_audio", result)
        persist.assert_called_once()

    def test_gpt_sovits_rejects_edge_voice_id_as_reference_path(self):
        with patch("src.server.runtime_settings._engine_available", return_value=True):
            with self.assertRaises(SettingsError) as ctx:
                apply_tts_settings(
                    Config(),
                    {
                        "type": "gpt-sovits",
                        "ref_file": "zh-TW-YunJheNeural",
                        "tts_server": "http://127.0.0.1:9880",
                    },
                    session_count=0,
                )
        self.assertIn("zh-TW-YunJheNeural", ctx.exception.message)
        self.assertIn("完整路徑", ctx.exception.message)

    def test_edge_tts_rejects_non_zh_tw_voice(self):
        with patch("src.server.runtime_settings._engine_available", return_value=True):
            with self.assertRaises(SettingsError) as ctx:
                apply_tts_settings(
                    Config(),
                    {"type": "edgetts", "ref_file": "zh-CN-XiaoxiaoNeural"},
                    session_count=0,
                )
        self.assertIn("台灣華語聲線", ctx.exception.message)

    def test_stt_prewarms_before_commit(self):
        config = Config()
        candidate = Mock()
        with patch("src.server.runtime_settings._engine_available", return_value=True), patch(
            "src.server.runtime_settings.create_asr_engine", return_value=candidate
        ), patch("src.server.runtime_settings.activate_asr_engine"), patch(
            "src.server.runtime_settings.persist_runtime_overrides"
        ) as persist:
            result = apply_stt_settings(
                config,
                {
                    "type": "whisper",
                    "model_size": "small",
                    "language": "auto",
                    "output_script": "traditional-tw",
                    "device": "cuda",
                },
                session_count=0,
            )
        candidate.ensure_ready.assert_called_once()
        self.assertEqual(result["model_size"], "small")
        self.assertEqual(result["output_script"], "traditional-tw")
        self.assertEqual(config.asr.output_script, "traditional-tw")
        self.assertEqual(config.asr.device, "cuda")
        persist.assert_called_once()

    def test_removed_qwen_speech_engines_are_rejected(self):
        with self.assertRaises(SettingsError):
            apply_stt_settings(
                Config(),
                {"type": "qwen3-asr", "model_size": "Qwen/Qwen3-ASR-0.6B"},
                session_count=0,
            )
        with self.assertRaises(SettingsError):
            apply_tts_settings(
                Config(),
                {"type": "qwen3-tts", "model": "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"},
                session_count=0,
            )
        snapshot = speech_snapshot(Config())
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
            suggest_avatar_id("wav2lip", "silent.mp4", set()),
            "wav2lip_silent",
        )


class LlamaCppCatalogTests(unittest.TestCase):
    def test_lists_and_resolves_gguf(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            gguf = folder / "LFM2.5-2.6B-Q4_K_M.gguf"
            gguf.write_bytes(b"fake")
            models = list_gguf_models(str(folder))
            names = [item["name"] for item in models]
            self.assertIn("LFM2.5-2.6B-Q4_K_M", names)
            self.assertEqual(resolve_gguf("LFM2.5-2.6B-Q4_K_M", str(folder)), gguf)

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
            {"id": "wav2lip256_avatar1", "type": "wav2lip"},
        ]
        engines = [
            {"id": "musetalk", "available": True, "message": ""},
            {"id": "wav2lip", "available": True, "message": ""},
        ]

        def boom(_config):
            raise FileNotFoundError("missing weights")

        with patch(
            "src.server.runtime_settings.list_avatar_characters",
            return_value=characters,
        ), patch(
            "src.server.runtime_settings.list_engines",
            return_value=engines,
        ), patch(
            "src.avatars.factory.prepare_avatar_model",
            side_effect=boom,
        ):
            with self.assertRaises(SettingsError):
                apply_avatar(config, "wav2lip", "wav2lip256_avatar1", session_count=0)

        self.assertEqual(config.model.type, "musetalk")
        self.assertEqual(config.model.avatar_id, "musetalk_avatar1")


if __name__ == "__main__":
    unittest.main()
