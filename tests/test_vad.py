import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.loader import dict_to_config
from src.vad.audio import decode_audio, pcm16_to_wav_bytes, resample_int16
from src.vad.base import BaseVAD, to_int16
from src.vad.engines import SileroVAD
from src.vad.factory import (
    create_vad_engine,
    get_vad_engine,
    list_vad_types,
    release_vad_engine,
)
from src.vad.segmenter import VADSegmenter, detect_speech_segments, extract_speech
from src.vad.service import preprocess_audio_bytes

SR = 16000


def _has(module: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(module) is not None


class EnergyVAD(BaseVAD):
    """測試用假引擎：能量超過閾值就算語音，不依賴任何第三方庫"""

    ENGINE_TYPE = "energy"
    SUPPORTED_SAMPLE_RATES = (16000,)
    DEFAULT_FRAME_MS = 20

    def _load_model(self):
        self.loaded = True

    def _speech_prob(self, frame: np.ndarray) -> float:
        return 1.0 if np.abs(frame).max() > 1000 else 0.0


def silence(ms: int) -> np.ndarray:
    return np.zeros(int(SR * ms / 1000), dtype=np.int16)


def tone(ms: int, amplitude: int = 8000) -> np.ndarray:
    t = np.arange(int(SR * ms / 1000)) / SR
    return (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.int16)


class BaseVADTests(unittest.TestCase):
    def test_frame_geometry(self):
        vad = EnergyVAD(sample_rate=SR, frame_ms=20)
        self.assertEqual(vad.frame_samples, 320)
        self.assertEqual(vad.frame_bytes, 640)

    def test_rejects_unsupported_sample_rate(self):
        with self.assertRaises(ValueError):
            EnergyVAD(sample_rate=44100)

    def test_frames_drop_partial_tail(self):
        vad = EnergyVAD(sample_rate=SR, frame_ms=20)
        frames = list(vad.frames(np.zeros(320 * 3 + 17, dtype=np.int16)))
        self.assertEqual(len(frames), 3)
        self.assertTrue(all(len(f) == 320 for f in frames))

    def test_wrong_frame_length_raises(self):
        vad = EnergyVAD(sample_rate=SR, frame_ms=20)
        with self.assertRaises(ValueError):
            vad.speech_prob(np.zeros(100, dtype=np.int16))

    def test_to_int16_accepts_bytes_and_float(self):
        pcm = np.array([-32768, 0, 32767], dtype=np.int16)
        self.assertTrue(np.array_equal(to_int16(pcm.tobytes()), pcm))
        self.assertTrue(np.array_equal(to_int16(np.array([0.0, 0.5], dtype=np.float32)),
                                       np.array([0, 16384], dtype=np.int16)))

    def test_lazy_model_load(self):
        vad = EnergyVAD(sample_rate=SR)
        self.assertFalse(vad.get_info()["initialized"])
        vad.speech_prob(silence(20))
        self.assertTrue(vad.get_info()["initialized"])


class SegmenterTests(unittest.TestCase):
    def _segmenter(self, **kwargs):
        params = dict(
            speech_start_ms=60,
            min_speech_ms=200,
            min_silence_ms=300,
            speech_pad_ms=100,
            max_speech_ms=0,
        )
        params.update(kwargs)
        return VADSegmenter(EnergyVAD(sample_rate=SR, frame_ms=20), **params)

    def test_single_segment_with_padding(self):
        audio = np.concatenate([silence(500), tone(800), silence(800)])
        segments = list(self._segmenter().process(audio))

        self.assertEqual(len(segments), 1)
        seg = segments[0]
        # 語音在 500~1300ms，前後各留 100ms padding（允許一幀誤差）
        self.assertAlmostEqual(seg.start_ms, 400, delta=40)
        self.assertAlmostEqual(seg.end_ms, 1400, delta=60)
        self.assertEqual(len(seg.audio), int(SR * seg.duration_ms / 1000))

    def test_two_segments_split_by_silence(self):
        audio = np.concatenate([silence(300), tone(600), silence(700), tone(600), silence(700)])
        segments = list(self._segmenter().process(audio))
        self.assertEqual(len(segments), 2)
        self.assertLess(segments[0].end_ms, segments[1].start_ms)

    def test_short_blip_discarded(self):
        # padding 會把片段撐到 200ms 以上，min_speech_ms 必須只看真實語音時長
        audio = np.concatenate([silence(300), tone(80), silence(800)])
        self.assertEqual(list(self._segmenter().process(audio)), [])

    def test_segment_reports_speech_ms(self):
        audio = np.concatenate([silence(300), tone(600), silence(700)])
        seg = list(self._segmenter().process(audio))[0]
        self.assertAlmostEqual(seg.speech_ms, 600, delta=60)
        self.assertLess(seg.speech_ms, seg.duration_ms)

    def test_endpoint_reports_how_long_vad_held_speech_after_the_voice_ended(self):
        # Clicks keep the VAD in speech while the audio is already below the
        # -40 dBFS voiced level: that is the post-speech tail before the
        # silence wait starts counting.
        click = np.zeros(320, dtype=np.int16)
        click[0] = 2000
        audio = np.concatenate([silence(300), tone(600), np.tile(click, 3), silence(700)])
        seg = list(self._segmenter().process(audio))[0]
        self.assertEqual(seg.endpoint_wait_ms, 300)
        self.assertEqual(seg.speech_tail_ms, 60)

        plain = list(self._segmenter().process(
            np.concatenate([silence(300), tone(600), silence(700)])))[0]
        self.assertEqual(plain.speech_tail_ms, 0)

    def test_only_an_endpoint_measures_the_speech_tail(self):
        segmenter = self._segmenter()
        self.assertEqual(list(segmenter.process(np.concatenate([silence(300), tone(800)]))), [])
        self.assertIsNone(list(segmenter.flush())[0].speech_tail_ms)

    def test_voiced_end_ignores_leading_and_trailing_silence(self):
        from src.vad.audio import voiced_end_sample

        audio = np.concatenate([silence(200), tone(500), silence(900)])
        self.assertAlmostEqual(voiced_end_sample(audio) / SR, 0.7, delta=0.021)
        self.assertIsNone(voiced_end_sample(silence(1000), missing=None))
        with self.assertRaises(ValueError):
            voiced_end_sample(silence(1000))

    def test_max_speech_forces_cut(self):
        audio = np.concatenate([silence(200), tone(3000), silence(600)])
        segments = list(self._segmenter(max_speech_ms=1000).process(audio))
        self.assertGreaterEqual(len(segments), 2)
        self.assertLessEqual(segments[0].duration_ms, 1020)

    def test_flush_closes_open_segment(self):
        segmenter = self._segmenter()
        audio = np.concatenate([silence(300), tone(800)])  # 沒有收尾靜音
        self.assertEqual(list(segmenter.process(audio)), [])
        self.assertTrue(segmenter.is_speaking)
        flushed = list(segmenter.flush())
        self.assertEqual(len(flushed), 1)
        self.assertFalse(segmenter.is_speaking)

    def test_streaming_chunks_match_single_shot(self):
        audio = np.concatenate([silence(400), tone(700), silence(700), tone(500), silence(600)])
        one_shot = detect_speech_segments(EnergyVAD(sample_rate=SR, frame_ms=20), audio,
                                          speech_start_ms=60, min_speech_ms=200,
                                          min_silence_ms=300, speech_pad_ms=100, max_speech_ms=0)

        segmenter = self._segmenter()
        streamed = []
        # 故意用和幀長不對齊的塊大小，驗證殘幀快取
        for start in range(0, len(audio), 777):
            streamed.extend(segmenter.process(audio[start:start + 777]))
        streamed.extend(segmenter.flush())

        self.assertEqual(
            [(s.start_ms, s.end_ms) for s in streamed],
            [(s.start_ms, s.end_ms) for s in one_shot],
        )

    def test_accepts_raw_bytes(self):
        audio = np.concatenate([silence(300), tone(700), silence(700)])
        segments = list(self._segmenter().process(audio.tobytes()))
        self.assertEqual(len(segments), 1)

    def test_extract_speech_drops_silence(self):
        audio = np.concatenate([silence(600), tone(700), silence(900)])
        speech = extract_speech(EnergyVAD(sample_rate=SR, frame_ms=20), audio,
                                speech_start_ms=60, min_speech_ms=200,
                                min_silence_ms=300, speech_pad_ms=100, max_speech_ms=0)
        self.assertIsNotNone(speech)
        self.assertLess(len(speech), len(audio))

    def test_extract_speech_returns_none_on_silence(self):
        self.assertIsNone(extract_speech(EnergyVAD(sample_rate=SR, frame_ms=20), silence(2000)))


class FrameNormalizationTests(unittest.TestCase):
    """構造引擎不會載入模型，所以沒裝第三方包也能驗證幀長約定"""

    def test_silero_fixed_frame_samples(self):
        self.assertEqual(SileroVAD(sample_rate=16000, frame_ms=30).frame_samples, 512)
        self.assertEqual(SileroVAD(sample_rate=8000).frame_samples, 256)

    def test_silero_rejects_unsupported_rate(self):
        with self.assertRaises(ValueError):
            SileroVAD(sample_rate=48000)


class FactoryTests(unittest.TestCase):
    def tearDown(self):
        release_vad_engine()

    def test_create_by_type_and_alias(self):
        self.assertIsInstance(create_vad_engine("silero"), SileroVAD)
        self.assertIsInstance(create_vad_engine("silero_vad"), SileroVAD)

    def test_unknown_type_raises(self):
        with self.assertRaises(ValueError):
            create_vad_engine("nope")
        self.assertEqual(list_vad_types(), ["silero"])

    def test_singleton_reuses_same_configuration(self):
        first = get_vad_engine("silero", sample_rate=SR)
        self.assertIs(get_vad_engine("silero", sample_rate=SR), first)

    def test_singleton_rebuilds_on_param_change(self):
        first = get_vad_engine("silero", sample_rate=SR, threshold=0.5)
        self.assertIsNot(get_vad_engine("silero", sample_rate=SR, threshold=0.8), first)


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        vad = dict_to_config({}).vad
        self.assertTrue(vad.enabled)
        self.assertEqual(vad.type, "silero")
        self.assertEqual(vad.sample_rate, 16000)

    def test_yaml_override(self):
        vad = dict_to_config({"vad": {"type": "silero", "threshold": 0.7, "enabled": False}}).vad
        self.assertEqual(vad.type, "silero")
        self.assertEqual(vad.threshold, 0.7)
        self.assertFalse(vad.enabled)


class AudioUtilTests(unittest.TestCase):
    def test_wav_roundtrip(self):
        pcm = tone(500)
        decoded = decode_audio(pcm16_to_wav_bytes(pcm, SR), SR)
        self.assertEqual(len(decoded), len(pcm))
        self.assertTrue(np.allclose(decoded, pcm, atol=2))

    def test_resample_changes_length(self):
        pcm = tone(1000)
        self.assertAlmostEqual(len(resample_int16(pcm, SR, 8000)), SR // 2, delta=10)

    def test_decode_rejects_garbage(self):
        with self.assertRaises(ValueError):
            decode_audio(b"not audio at all", SR)


class _VADCfg:
    """模擬 config.vad"""
    def __init__(self, **kwargs):
        self.enabled = True
        self.type = "silero"
        self.sample_rate = SR
        self.frame_ms = 0
        self.threshold = 0.5
        self.aggressiveness = 2
        self.device = "cpu"
        self.model_path = ""
        self.use_onnx = False
        self.speech_start_ms = 100
        self.min_speech_ms = 250
        self.min_silence_ms = 500
        self.speech_pad_ms = 150
        self.max_speech_ms = 15000
        self.__dict__.update(kwargs)


class ServiceTests(unittest.TestCase):
    def tearDown(self):
        release_vad_engine()

    def test_disabled_passthrough(self):
        raw = pcm16_to_wav_bytes(tone(300), SR)
        outcome = preprocess_audio_bytes(raw, _VADCfg(enabled=False))
        self.assertFalse(outcome.enabled)
        self.assertTrue(outcome.has_speech)
        self.assertIs(outcome.audio_bytes, raw)

    def test_no_config_passthrough(self):
        raw = pcm16_to_wav_bytes(tone(300), SR)
        self.assertIs(preprocess_audio_bytes(raw, None).audio_bytes, raw)

    def test_broken_audio_degrades_to_original(self):
        outcome = preprocess_audio_bytes(b"garbage", _VADCfg())
        self.assertTrue(outcome.has_speech)  # 失敗不能擋住 ASR
        self.assertTrue(outcome.error)
        self.assertEqual(outcome.audio_bytes, b"garbage")


def _speech_like(duration_ms: int, seed: int = 0) -> np.ndarray:
    """帶基頻抖動和音節包絡的合成語音，真引擎能識別成語音"""
    rng = np.random.default_rng(seed)
    t = np.arange(int(SR * duration_ms / 1000)) / SR
    f0 = 120 + 20 * np.sin(2 * np.pi * 3 * t)
    phase = 2 * np.pi * np.cumsum(f0) / SR
    sig = sum(np.sin(k * phase) / k for k in range(1, 15))
    sig = sig * (0.5 + 0.5 * np.sin(2 * np.pi * 4.5 * t)) + 0.02 * rng.standard_normal(len(t))
    return (sig / np.max(np.abs(sig)) * 0.6 * 32767).astype(np.int16)


@unittest.skipUnless(_has("silero_vad"), "未安裝 silero-vad")
class SileroEngineTests(unittest.TestCase):
    def tearDown(self):
        release_vad_engine()

    def test_detects_speech_and_ignores_silence(self):
        vad = get_vad_engine("silero", sample_rate=SR)
        vad.reset()
        audio = np.concatenate([silence(600), _speech_like(1200), silence(800)])
        segments = detect_speech_segments(vad, audio)
        self.assertEqual(len(segments), 1)

        vad.reset()
        self.assertEqual(detect_speech_segments(vad, silence(2000)), [])

    def test_service_trims_silence(self):
        audio = np.concatenate([silence(1000), _speech_like(1000), silence(1000)])
        outcome = preprocess_audio_bytes(pcm16_to_wav_bytes(audio, SR), _VADCfg(type="silero"))
        self.assertTrue(outcome.has_speech)
        self.assertLess(outcome.speech_ms, outcome.total_ms)
        self.assertGreater(outcome.trimmed_ms, 0)

    def test_service_reports_no_speech(self):
        outcome = preprocess_audio_bytes(pcm16_to_wav_bytes(silence(2000), SR), _VADCfg(type="silero"))
        self.assertFalse(outcome.has_speech)
        self.assertFalse(outcome.error)


class SettingsApiTests(unittest.TestCase):
    """設定面板走的 apply_vad_settings：切引擎、夾取值範圍、缺依賴時明確報錯"""

    def setUp(self):
        self.config = dict_to_config({})
        patcher = patch("src.server.runtime_settings.persist_runtime_overrides")
        self.persist = patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(release_vad_engine)

    def test_snapshot_is_always_server_side(self):
        from src.server.runtime_settings import vad_snapshot

        self.config.asr.mode = "browser"
        snapshot = vad_snapshot(self.config)
        self.assertTrue(snapshot["enabled"])
        self.assertTrue(snapshot["effective"])
        self.assertEqual(snapshot["asr_mode"], "server")

    def test_silero_is_enforced_and_persisted(self):
        from src.server.runtime_settings import SettingsError, apply_vad_settings

        with self.assertRaises(SettingsError):
            apply_vad_settings(self.config, {"type": "webrtc"})
        result = apply_vad_settings(self.config, {"type": "silero"})
        self.assertEqual(result["type"], "silero")
        self.assertEqual(self.config.vad.type, "silero")
        self.assertEqual(self.config.asr.mode, "server")
        self.assertTrue(self.persist.called)

    def test_values_are_clamped(self):
        from src.server.runtime_settings import apply_vad_settings

        result = apply_vad_settings(self.config, {"threshold": 9, "min_silence_ms": -5})
        self.assertEqual(result["threshold"], 0.95)
        self.assertEqual(result["min_silence_ms"], 100)

    def test_unknown_engine_rejected(self):
        from src.server.runtime_settings import SettingsError, apply_vad_settings

        with self.assertRaises(SettingsError):
            apply_vad_settings(self.config, {"type": "kaldi"})

    def test_missing_dependency_reports_install_command(self):
        from src.server.runtime_settings import SettingsError, apply_vad_settings

        with patch("src.server.runtime_settings._module_installed", return_value=False):
            with self.assertRaises(SettingsError) as ctx:
                apply_vad_settings(self.config, {"type": "silero", "enabled": True})
        self.assertIn("silero-vad", ctx.exception.message)

    def test_disable_skips_dependency_check(self):
        from src.server.runtime_settings import apply_vad_settings

        with patch("src.server.runtime_settings._module_installed", return_value=False):
            result = apply_vad_settings(self.config, {"enabled": False})
        self.assertFalse(result["enabled"])


if __name__ == "__main__":
    unittest.main()
