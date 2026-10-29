import math
import sys
import time
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import soundfile as sf

from src.asr.base import BaseASR, asr_language
from src.asr.engines.whisper import WhisperASR


class WhisperASRLoadingTests(unittest.TestCase):
    def test_loads_faster_whisper_with_cpu_int8(self):
        engine = WhisperASR.__new__(WhisperASR)
        engine.model_size = "base"
        engine.device = "cpu"
        engine.compute_type = "int8"
        engine.model = None
        engine.model_type = None

        faster_whisper = types.ModuleType("faster_whisper")
        model = object()
        faster_whisper.WhisperModel = Mock(return_value=model)

        with patch.dict(
            sys.modules,
            {"faster_whisper": faster_whisper},
        ):
            engine._load_model()

        self.assertIs(engine.model, model)
        self.assertEqual(engine.model_type, "faster-whisper")
        faster_whisper.WhisperModel.assert_called_once_with(
            "base",
            device="cpu",
            compute_type="int8",
        )


def _wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    buffer = BytesIO()
    sf.write(buffer, samples, sample_rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


def _ready_engine(model) -> WhisperASR:
    engine = WhisperASR.__new__(WhisperASR)
    BaseASR.__init__(engine, None)
    engine.model_size = "small"
    engine.device = "cpu"
    engine.compute_type = "int8"
    engine.model = model
    engine.model_type = "faster-whisper"
    engine._initialized = True
    return engine


class WhisperASRTranscribeTests(unittest.TestCase):
    def setUp(self):
        self.model = Mock()
        self.model.transcribe.return_value = (
            iter([SimpleNamespace(start=0.0, end=0.5, text=" 你好", avg_logprob=-0.1)]),
            SimpleNamespace(language="zh"),
        )
        # The voice pipeline must never touch the filesystem per turn.
        no_temp = patch("tempfile.mkstemp", side_effect=AssertionError("temp file written"))
        no_temp.start()
        self.addCleanup(no_temp.stop)

    def test_16k_wav_is_decoded_in_memory_and_decoded_greedily(self):
        samples = (np.sin(np.linspace(0, 200, 16000)) * 8000).astype(np.int16)
        engine = _ready_engine(self.model)

        result = engine.transcribe(_wav_bytes(samples, 16000), language="zh")

        audio = self.model.transcribe.call_args.args[0]
        kwargs = self.model.transcribe.call_args.kwargs
        self.assertIsInstance(audio, np.ndarray)
        self.assertEqual(audio.dtype, np.float32)
        np.testing.assert_allclose(audio, samples / 32768.0, atol=1e-4)
        self.assertEqual(kwargs["language"], "zh")
        self.assertEqual(kwargs["beam_size"], 1)
        self.assertFalse(kwargs["vad_filter"])
        self.assertEqual(result["text"], "你好")
        self.assertAlmostEqual(result["confidence"], math.exp(-0.1))

    def test_stereo_audio_is_downmixed_to_mono(self):
        left = np.full(1600, 4000, dtype=np.int16)
        right = np.full(1600, 2000, dtype=np.int16)
        engine = _ready_engine(self.model)

        engine.transcribe(_wav_bytes(np.stack([left, right], axis=1), 16000), language="en")

        audio = self.model.transcribe.call_args.args[0]
        self.assertEqual(audio.shape, (1600,))
        np.testing.assert_allclose(audio, 3000 / 32768.0, atol=1e-4)

    def test_other_sample_rates_and_containers_stay_in_memory(self):
        engine = _ready_engine(self.model)
        for payload in (_wav_bytes(np.ones(4800, dtype=np.int16), 48000), b"not-a-wav"):
            with self.subTest(size=len(payload)):
                engine.transcribe(payload, language="zh")
                audio = self.model.transcribe.call_args.args[0]
                # faster-whisper decodes and resamples file-like input with PyAV.
                self.assertIsInstance(audio, BytesIO)
                self.assertEqual(audio.getvalue(), payload)

    def test_auto_language_still_lets_whisper_detect(self):
        engine = _ready_engine(self.model)

        engine.transcribe(_wav_bytes(np.ones(1600, dtype=np.int16), 16000), language="auto")

        self.assertIsNone(self.model.transcribe.call_args.kwargs["language"])


class ConversationLanguageTests(unittest.TestCase):
    def test_conversation_locale_maps_to_a_fixed_recognizer_language(self):
        self.assertEqual(asr_language("zh-TW"), "zh")
        self.assertEqual(asr_language("en-US"), "en")
        with self.assertRaises(ValueError):
            asr_language("ja-JP")


class ASRFactoryConcurrencyTests(unittest.TestCase):
    def test_concurrent_sessions_load_one_shared_engine(self):
        from src.asr import factory

        first_create_started = Event()
        release_create = Event()
        count_lock = Lock()
        create_count = 0

        def slow_create(**_kwargs):
            nonlocal create_count
            with count_lock:
                create_count += 1
            first_create_started.set()
            release_create.wait(timeout=0.5)
            return SimpleNamespace(set_language=Mock())

        config = SimpleNamespace(
            asr=SimpleNamespace(device="cpu", language="zh")
        )
        old_instance = factory._asr_instance
        old_key = factory._asr_instance_key
        factory._asr_instance = None
        factory._asr_instance_key = None
        try:
            with (
                patch("src.asr.factory.create_asr_engine", side_effect=slow_create),
                ThreadPoolExecutor(max_workers=2) as executor,
            ):
                first = executor.submit(
                    factory.get_asr_engine, "whisper", "tiny", config
                )
                self.assertTrue(first_create_started.wait(timeout=0.5))
                second = executor.submit(
                    factory.get_asr_engine, "whisper", "tiny", config
                )
                time.sleep(0.02)
                release_create.set()
                first_engine = first.result(timeout=0.5)
                second_engine = second.result(timeout=0.5)

            self.assertEqual(create_count, 1)
            self.assertIs(first_engine, second_engine)
        finally:
            release_create.set()
            factory._asr_instance = old_instance
            factory._asr_instance_key = old_key


if __name__ == "__main__":
    unittest.main()
