# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np

from scripts.qwen3_tts_server import Qwen3Synthesizer, require_loopback


class FakeModel:
    def __init__(self, sample_rate=24000):
        self.sample_rate = sample_rate
        self.yield_rate = sample_rate
        self.calls = []

    def _chunks(self):
        yield np.array([0.5, -0.5, 2.0], dtype=np.float32), self.yield_rate, {}
        yield np.array([0.25], dtype=np.float32), self.yield_rate, {}

    def generate_voice_clone_streaming(self, **kwargs):
        kwargs["ref_audio_bytes"] = Path(kwargs["ref_audio"]).read_bytes()
        self.calls.append(("clone", kwargs))
        return self._chunks()

    def generate_custom_voice_streaming(self, **kwargs):
        self.calls.append(("custom", kwargs))
        return self._chunks()


class LoopbackTests(unittest.TestCase):
    def test_only_loopback_hosts_are_accepted(self):
        for host in ("127.0.0.1", "::1", "localhost"):
            require_loopback(host)
        for host in ("0.0.0.0", "192.168.1.5", "example.com"):
            with self.assertRaises(ValueError):
                require_loopback(host)


class SynthesizerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.model = FakeModel()

    def tearDown(self):
        self.tmp.cleanup()

    def synthesizer(self, **kwargs):
        return Qwen3Synthesizer(self.model, prompt_dir=Path(self.tmp.name), chunk_size=4, **kwargs)

    def test_reports_the_model_sample_rate(self):
        self.model.sample_rate = self.model.yield_rate = 16000
        self.assertEqual(self.synthesizer().sample_rate, 16000)

    def test_clones_the_uploaded_voice_and_streams_pcm16(self):
        pcm = b"".join(self.synthesizer().stream("歡迎來到臺北。", "參考逐字稿", b"RIFF-voice", "Chinese"))

        np.testing.assert_array_equal(np.frombuffer(pcm, np.int16), [16384, -16384, 32767, 8192])
        mode, kwargs = self.model.calls[0]
        self.assertEqual(mode, "clone")
        self.assertEqual((kwargs["text"], kwargs["ref_text"], kwargs["language"], kwargs["chunk_size"]),
                         ("歡迎來到臺北。", "參考逐字稿", "Chinese", 4))
        self.assertEqual(kwargs["ref_audio_bytes"], b"RIFF-voice")

    def test_the_same_reference_reuses_one_path_so_the_voice_prompt_cache_hits(self):
        synthesizer = self.synthesizer()
        for _ in range(2):
            b"".join(synthesizer.stream("你好。", "參考", b"same-voice", "Chinese"))
        b"".join(synthesizer.stream("你好。", "參考", b"other-voice", "Chinese"))
        paths = [kwargs["ref_audio"] for _, kwargs in self.model.calls]
        self.assertEqual(paths[0], paths[1])
        self.assertNotEqual(paths[0], paths[2])

    def test_custom_voice_mode_uses_the_configured_speaker(self):
        b"".join(self.synthesizer(speaker="vivian").stream("Hello.", "", b"ignored", "English"))
        mode, kwargs = self.model.calls[0]
        self.assertEqual((mode, kwargs["speaker"], kwargs["language"]), ("custom", "vivian", "English"))

    def test_rejects_unknown_languages_and_unexpected_sample_rates(self):
        with self.assertRaises(ValueError):
            next(self.synthesizer().stream("你好。", "", b"v", "Klingon"))
        self.model.yield_rate = 22050
        with self.assertRaises(RuntimeError):
            b"".join(self.synthesizer().stream("你好。", "", b"v", "Chinese"))


@unittest.skipUnless(importlib.util.find_spec("fastapi") and importlib.util.find_spec("httpx"),
                     "FastAPI runs only in the Qwen3-TTS environment")
class AppTests(unittest.TestCase):
    def test_health_and_zero_shot_contract(self):
        from fastapi.testclient import TestClient

        from scripts.qwen3_tts_server import create_app

        with tempfile.TemporaryDirectory() as directory:
            synthesizer = Qwen3Synthesizer(FakeModel(), prompt_dir=Path(directory), chunk_size=4)
            client = TestClient(create_app(synthesizer, model_name="fake"))
            health = client.get("/health").json()
            self.assertEqual((health["family"], health["sample_rate"]), ("qwen3-tts", 24000))
            response = client.post("/inference_zero_shot",
                                   data={"tts_text": "你好。", "prompt_text": "參考", "language": "Chinese"},
                                   files={"prompt_wav": ("p.wav", b"voice", "application/octet-stream")})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.content), 8)
            bad = client.post("/inference_zero_shot", data={"tts_text": "x", "language": "Klingon"},
                              files={"prompt_wav": ("p.wav", b"voice", "application/octet-stream")})
            self.assertEqual(bad.status_code, 400)
