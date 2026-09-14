import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import soundfile as sf

from src.tts.cosyvoice_runtime import (
    COSYVOICE_LANGUAGES,
    build_instruct,
    normalize_language,
    prepare_prompt_wav,
    trim_prompt_speech,
)
from src.tts.engines.cosyvoice import CosyVoiceTTS, DEFAULT_PROMPT_TEXT


def _write_wav(path: str, duration_s: float = 1.0, sr: int = 16000) -> None:
    n = int(sr * duration_s)
    sf.write(path, np.zeros(n, dtype=np.float32), sr)


def _tts(
    *,
    mode: str = "auto",
    language: str = "zh",
    instruct: str = "",
    ref_file: str = "",
    ref_text: str = "",
) -> CosyVoiceTTS:
    engine = CosyVoiceTTS.__new__(CosyVoiceTTS)
    engine.config = SimpleNamespace(
        tts=SimpleNamespace(
            mode=mode,
            language=language,
            instruct=instruct,
            ref_file=ref_file,
            ref_text=ref_text,
            tts_server="http://127.0.0.1:50000",
        )
    )
    engine.sample_rate = 16000
    return engine


class CosyVoiceRuntimeTests(unittest.TestCase):
    def test_normalize_language_maps_aliases(self) -> None:
        self.assertEqual(normalize_language("Chinese"), "zh")
        self.assertEqual(normalize_language("jp"), "ja")
        self.assertEqual(normalize_language("zh-TW"), "zh")
        self.assertEqual(normalize_language("auto"), "auto")
        self.assertEqual(normalize_language(""), "zh")

    def test_convert_prompt_writes_24k_mono_under_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "prompt.wav")
            _write_wav(src, duration_s=2.0, sr=48000)
            out = prepare_prompt_wav(src, cache_dir=Path(tmp))
            self.assertTrue(str(out).endswith(".cosy24k.v2.wav"))
            self.assertTrue(out.is_file())
            data, sr = sf.read(out)
            self.assertEqual(sr, 24000)
            self.assertLessEqual(len(data) / 24000, 8.01)

    def test_convert_prompt_trims_leading_silence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "prompt.wav")
            sr = 16000
            silence = np.zeros(int(sr * 0.4), dtype=np.float32)
            speech = np.full(int(sr * 0.6), 0.2, dtype=np.float32)
            sf.write(src, np.concatenate([silence, speech]), sr)
            out = prepare_prompt_wav(src, cache_dir=Path(tmp))
            data, out_sr = sf.read(out)
            self.assertGreater(float(np.abs(data).mean()), 0.05)
            self.assertLess(len(data) / out_sr, 0.85)

    def test_trim_prompt_speech_keeps_first_spoken_window(self) -> None:
        sr = 16000
        silence = np.zeros(int(sr * 0.5), dtype=np.float32)
        speech = np.full(int(sr * 0.4), 0.3, dtype=np.float32)
        audio = np.concatenate([silence, speech, np.zeros(int(sr * 0.2), dtype=np.float32)])
        trimmed = trim_prompt_speech(audio, sr, max_seconds=8.0)
        self.assertGreaterEqual(len(trimmed) / sr, 0.4)
        self.assertLessEqual(len(trimmed) / sr, 0.85)
        self.assertGreater(float(np.abs(trimmed).mean()), 0.15)

    def test_prepare_prompt_wav_resolves_cosyvoice_asset_basename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            asset_dir = Path(tmp) / "CosyVoice" / "asset"
            asset_dir.mkdir(parents=True)
            asset = asset_dir / "SHINeeJonghyun.mp3"
            _write_wav(str(asset), duration_s=1.0, sr=48000)
            cache = Path(tmp) / "cache"
            with patch("src.tts.cosyvoice_runtime.Path.home", return_value=Path(tmp)):
                out = prepare_prompt_wav("SHINeeJonghyun.mp3", cache_dir=cache)
            self.assertTrue(out.is_file())
            self.assertTrue(str(out).endswith(".cosy24k.v2.wav"))

    def test_build_instruct_uses_language_when_custom_empty(self) -> None:
        self.assertEqual(build_instruct("zh", ""), "用中文说这句话<|endofprompt|>")
        self.assertEqual(build_instruct("ja", ""), "日本語で話してください<|endofprompt|>")
        self.assertEqual(
            build_instruct("en", "speak slowly"),
            "Speak this in English，speak slowly<|endofprompt|>",
        )
        self.assertEqual(build_instruct("auto", ""), "")

    def test_build_instruct_v3_uses_assistant_prefix(self) -> None:
        self.assertEqual(
            build_instruct("zh", "", family="cosyvoice3"),
            "You are a helpful assistant. 请用中文说这句话。<|endofprompt|>",
        )
        self.assertEqual(
            build_instruct("yue", "语速稍慢", family="cosyvoice3"),
            "You are a helpful assistant. 请用广东话表达。 语速稍慢<|endofprompt|>",
        )
        self.assertEqual(build_instruct("auto", "", family="cosyvoice3"), "")

    def test_languages_include_zh_ja_en(self) -> None:
        codes = {item[0] for item in COSYVOICE_LANGUAGES}
        self.assertTrue({"zh", "ja", "en", "yue", "ko", "auto"}.issubset(codes))


class CosyVoiceTTSClientTests(unittest.TestCase):
    def test_custom_prompt_without_ref_text_uses_cross_lingual(self) -> None:
        tts = _tts(language="auto", ref_text="")
        endpoint, payload = tts._tts_request("你好。", "")
        self.assertEqual(endpoint, "inference_cross_lingual")
        self.assertNotIn("prompt_text", payload)
        self.assertNotIn("instruct_text", payload)

    def test_default_prompt_keeps_zero_shot_when_no_language(self) -> None:
        tts = _tts(language="auto", ref_text=DEFAULT_PROMPT_TEXT)
        endpoint, payload = tts._tts_request("你好。", DEFAULT_PROMPT_TEXT)
        self.assertEqual(endpoint, "inference_zero_shot")
        self.assertEqual(payload["prompt_text"], DEFAULT_PROMPT_TEXT)
        self.assertNotIn("instruct_text", payload)

    def test_auto_language_only_uses_cross_lingual(self) -> None:
        tts = _tts(language="zh", ref_text="")
        endpoint, payload = tts._tts_request("你好，今天天氣很好。", "")
        self.assertEqual(endpoint, "inference_cross_lingual")
        self.assertNotIn("prompt_text", payload)

    def test_config_chinese_alias_with_reference_uses_zero_shot(self) -> None:
        tts = _tts(language="Chinese")
        endpoint, payload = tts._tts_request("你好。", DEFAULT_PROMPT_TEXT)
        self.assertEqual(endpoint, "inference_zero_shot")

    def test_zero_shot_ignores_language(self) -> None:
        tts = _tts(language="zh", ref_text="")
        for language in ("Chinese", "zh", "auto"):
            tts = _tts(mode="zero_shot", language=language, ref_text="你好")
            tts.config.tts.type = "fun-cosyvoice3"
            endpoint, _ = tts._tts_request("你好。", "你好")
            self.assertEqual(endpoint, "inference_zero_shot")

    def test_zero_shot_requires_reference_text(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires tts.ref_text"):
            _tts(mode="zero_shot")._tts_request("你好。", "")

    def test_explicit_modes_select_expected_endpoints(self) -> None:
        self.assertEqual(_tts(mode="cross_lingual", language="zh", ref_text="x")._tts_request("x", "x")[0], "inference_cross_lingual")
        self.assertEqual(_tts(mode="instruct", language="Chinese", instruct="溫柔", ref_text="x")._tts_request("x", "x")[0], "inference_instruct2")

    def test_fun_cosyvoice3_zero_shot_wraps_prompt_text(self) -> None:
        tts = _tts(language="auto", ref_text=DEFAULT_PROMPT_TEXT)
        tts.config.tts.type = "fun-cosyvoice3"
        endpoint, payload = tts._tts_request("你好。", DEFAULT_PROMPT_TEXT)
        self.assertEqual(endpoint, "inference_zero_shot")
        self.assertTrue(
            payload["prompt_text"].startswith("You are a helpful assistant.<|endofprompt|>")
        )

    def test_fun_cosyvoice3_cross_lingual_wraps_tts_text(self) -> None:
        tts = _tts(mode="cross_lingual", language="zh")
        tts.config.tts.type = "fun-cosyvoice3"

        endpoint, payload = tts._tts_request("你好。", "")

        self.assertEqual(endpoint, "inference_cross_lingual")
        self.assertEqual(
            payload["tts_text"],
            "You are a helpful assistant.<|endofprompt|>你好。",
        )
        self.assertNotIn("prompt_text", payload)
        self.assertNotIn("instruct_text", payload)

    def test_custom_instruct_appends_after_language(self) -> None:
        tts = _tts(mode="instruct", language="ja", instruct="用開心的語氣說")
        endpoint, payload = tts._tts_request("你好。", DEFAULT_PROMPT_TEXT)
        self.assertEqual(endpoint, "inference_instruct2")
        self.assertEqual(
            payload["instruct_text"],
            "日本語で話してください，用開心的語氣說<|endofprompt|>",
        )

    def test_empty_stream_raises_after_notify(self) -> None:
        from src.tts.base import State

        tts = _tts()
        tts.state = State.RUNNING
        notified = []

        class FakeResponse:
            status_code = 200
            headers = {"content-type": "application/octet-stream"}
            text = ""

            def iter_content(self, chunk_size: int):
                del chunk_size
                if False:
                    yield b""

        tts.parent = SimpleNamespace(
            notify_fragment_synthesis_failed=lambda event, reason: notified.append(reason),
            put_audio_frame=lambda *args, **kwargs: None,
        )
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            path = handle.name
        try:
            _write_wav(path, duration_s=0.3)
            with patch.object(tts, "_prompt_wav", return_value=path):
                with patch("src.tts.engines.cosyvoice.requests.post", return_value=FakeResponse()):
                    with self.assertRaisesRegex(RuntimeError, "no decodable audio"):
                        tts.txt_to_audio(("你好", {"turn_id": "t1"}))
        finally:
            os.unlink(path)
        self.assertEqual(notified, ["tts_exhausted_before_audio"])

    def test_http_error_raises_after_notify(self) -> None:
        from src.tts.base import State

        tts = _tts()
        tts.state = State.RUNNING
        notified = []

        class FakeResponse:
            status_code = 400
            text = "frontend_instruct2 failed"

            def iter_content(self, chunk_size: int):
                del chunk_size
                return iter(())

        tts.parent = SimpleNamespace(
            notify_fragment_synthesis_failed=lambda event, reason: notified.append(reason),
            put_audio_frame=lambda *args, **kwargs: None,
        )
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            path = handle.name
        try:
            _write_wav(path, duration_s=0.3)
            with patch.object(tts, "_prompt_wav", return_value=path):
                with patch("src.tts.engines.cosyvoice.requests.post", return_value=FakeResponse()):
                    with self.assertRaisesRegex(RuntimeError, "HTTP 400"):
                        tts.txt_to_audio(("你好", {"turn_id": "t1"}))
        finally:
            os.unlink(path)
        self.assertEqual(notified, ["tts_exhausted_before_audio"])


if __name__ == "__main__":
    unittest.main()
