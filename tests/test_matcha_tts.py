# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the offline CPU/ONNX Matcha-TTS engine and config wiring."""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from src.config.schema import Config
from src.server.conversations import check_language_support
from src.server.reply_streaming.channel import PlayableFragment
from src.server.reply_streaming.turn import TurnEnvelope
from src.server.runtime_settings import (
    SettingsError,
    apply_tts_settings,
    speech_snapshot,
)
from src.tts.engines.matcha import (
    MatchaTTS,
    discover_matcha_models,
    normalize_matcha_text,
    resolve_matcha_model_paths,
)
from src.tts.factory import create_tts_engine

pytestmark = pytest.mark.speech


def _create_dummy_matcha_bundle(model_dir: Path) -> Path:
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "model.onnx").write_bytes(b"onnx")
    (model_dir / "vocos-16khz-univ.onnx").write_bytes(b"vocos")
    (model_dir / "tokens.txt").write_text("  1\nni3 2\nhao3 3\n", encoding="utf-8")
    (model_dir / "lexicon.txt").write_text(
        "什么 shen2 me5\n为什么 wei4 shen2 me5\n软件 ruan3 jian4\n"
        "nova n ˈ O v ə\navatar ˈ æ v ə t ˌ ɑ ɹ\nai ˈ A ˌ I\n"
        "a A\np p ˈ i\ni ˈ I\n",
        encoding="utf-8",
    )
    return model_dir


class _DummyParent:
    def __init__(self) -> None:
        self.frames: list[tuple[np.ndarray, dict]] = []
        self.stages: list[str] = []
        self.failures: list[tuple[dict, str]] = []

    def put_audio_frame(self, samples: np.ndarray, eventpoint: dict) -> None:
        self.frames.append((np.asarray(samples, dtype=np.float32).copy(), dict(eventpoint)))

    def mark_stage_end(self, name: str) -> None:
        self.stages.append(name)

    def notify_fragment_synthesis_failed(self, eventpoint: dict, reason: str) -> None:
        self.failures.append((dict(eventpoint), reason))


def _fake_sherpa_module(samples: np.ndarray, sample_rate: int = 16000):
    mod = types.ModuleType("sherpa_onnx")

    class _Cfg:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class _Audio:
        def __init__(self, s, sr):
            self.samples = s
            self.sample_rate = sr

    class _OfflineTts:
        last_instance = None

        def __init__(self, config):
            self.config = config
            self.calls: list[str] = []
            _OfflineTts.last_instance = self

        def generate(self, text: str, sid: int = 0, speed: float = 1.0, callback=None):
            self.calls.append(text)
            if callable(callback):
                callback(samples[: min(320, len(samples))], 0.5)
            return _Audio(samples, sample_rate)

    mod.OfflineTtsMatchaModelConfig = _Cfg
    mod.OfflineTtsModelConfig = _Cfg
    mod.OfflineTtsConfig = _Cfg
    mod.OfflineTts = _OfflineTts
    return mod


class MatchaModelDiscoveryTests(unittest.TestCase):
    def test_resolve_and_discover_prioritizes_trained_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local_dir = _create_dummy_matcha_bundle(root / ".local/tts-models/zh-tw-local")
            models_dir = _create_dummy_matcha_bundle(root / "models/tts/zh-tw-custom")

            found = discover_matcha_models(root)
            self.assertEqual(
                [item.model_dir for item in found],
                [models_dir.resolve(), local_dir.resolve()],
            )

            resolved = resolve_matcha_model_paths("", repo_root=root)
            self.assertEqual(resolved.model_dir, models_dir.resolve())
            self.assertEqual(resolved.acoustic_model.name, "model.onnx")

            resolved_onnx = resolve_matcha_model_paths(str(local_dir / "model.onnx"), repo_root=root)
            self.assertEqual(resolved_onnx.model_dir, local_dir.resolve())

    def test_resolve_raises_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                resolve_matcha_model_paths("models/tts/nonexistent", repo_root=Path(tmp))

    def test_discover_excludes_non_matcha_vits_and_kokoro_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            matcha_dir = _create_dummy_matcha_bundle(root / "models/tts/matcha-icefall-zh-en")

            vits_dir = root / "models/tts/vits-melo-tts-zh_en"
            vits_dir.mkdir(parents=True)
            (vits_dir / "model.onnx").write_bytes(b"vits")
            (vits_dir / "tokens.txt").write_text("  1\n", encoding="utf-8")
            (vits_dir / "lexicon.txt").write_text("你 ni3\n", encoding="utf-8")

            kokoro_dir = root / "models/tts/kokoro-int8-multi-lang-v1_1"
            kokoro_dir.mkdir(parents=True)
            (kokoro_dir / "model.int8.onnx").write_bytes(b"kokoro")
            (kokoro_dir / "voices.bin").write_bytes(b"voices")
            (kokoro_dir / "tokens.txt").write_text("  1\n", encoding="utf-8")
            (kokoro_dir / "lexicon.txt").write_text("a A\n", encoding="utf-8")

            found = discover_matcha_models(root)
            self.assertEqual([item.model_dir for item in found], [matcha_dir.resolve()])
            with self.assertRaises(FileNotFoundError):
                resolve_matcha_model_paths(str(vits_dir), repo_root=root)
            with self.assertRaises(FileNotFoundError):
                resolve_matcha_model_paths(str(kokoro_dir), repo_root=root)


class MatchaTextNormalizationTests(unittest.TestCase):
    def test_t2s_and_english_oov_acronym_expansion(self):
        lex = {"nova", "avatar", "ai", "a", "p", "i"}
        normalized = normalize_matcha_text(
            "為什麼 `NovaAvatar` 的 **API** 與 AI 軟體這麼快？",
            lexicon_words=lex,
            converter=None,
        )
        # Word-level traditional replacement + CamelCase split + OOV acronym spell-out
        self.assertIn("nova avatar", normalized)
        self.assertIn("a p i", normalized)
        self.assertIn("ai", normalized)
        self.assertIn("软件", normalized)

        from opencc import OpenCC

        t2s_norm = normalize_matcha_text(
            "繁體中文測試，什麼時候支援 API？",
            lexicon_words=lex,
            converter=OpenCC("t2s"),
        )
        self.assertIn("什么", t2s_norm)
        self.assertIn("a p i", t2s_norm)

    def test_cjk_dunhao_removed_without_splitting_clauses(self):
        norm = normalize_matcha_text("我會用自然、口語化的方式，提供準確、有用的資訊。")
        self.assertEqual(norm, "我會用自然口語化的方式，提供準確有用的資訊。")
        # Comma remains intact while CJK enumeration dunhao is elided
        self.assertIn("，", norm)


class MatchaEngineSynthesisTests(unittest.TestCase):
    def test_factory_and_turn_aware_fragment_emission(self):
        t = np.linspace(0.0, 0.2, 3200, endpoint=False, dtype=np.float32)
        wave = (0.3 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
        fake_mod = _fake_sherpa_module(wave, 16000)

        with tempfile.TemporaryDirectory() as tmp:
            bundle = _create_dummy_matcha_bundle(Path(tmp) / "zh-tw-custom")
            cfg = Config()
            cfg.tts.type = "matcha"
            cfg.tts.model = str(bundle)
            cfg.tts.num_threads = 4
            cfg.tts.length_scale = 0.95
            parent = _DummyParent()

            with patch.dict(sys.modules, {"sherpa_onnx": fake_mod}):
                engine = create_tts_engine("matcha", cfg, parent)
                self.assertIsInstance(engine, MatchaTTS)

                fragment = PlayableFragment(
                    envelope=TurnEnvelope(
                        turn_id="turn-1",
                        generation=2,
                        stage="tts",
                        sequence=0,
                    ),
                    text="繁體中文 API 測試",
                    estimated_seconds=1.2,
                )
                engine.synthesize_fragment(
                    fragment,
                    chunk_guard=lambda _seq: True,
                )

        self.assertEqual(len(parent.failures), 0)
        self.assertGreater(len(parent.frames), 0)
        self.assertEqual(parent.stages[:2], ["tts_pcm_available", "tts_first_pcm"])
        first_chunk, first_ep = parent.frames[0]
        last_chunk, last_ep = parent.frames[-1]
        self.assertEqual(first_chunk.shape, (320,))
        self.assertEqual(last_chunk.shape, (320,))
        self.assertEqual(first_ep["status"], "start")
        self.assertTrue(first_ep["fragment_start"])
        self.assertFalse(first_ep["fragment_end"])
        self.assertEqual(last_ep["status"], "end")
        self.assertTrue(last_ep["fragment_end"])
        self.assertIn("a p i", fake_mod.OfflineTts.last_instance.calls[0])

    def test_chunk_guard_cancels_emission(self):
        wave = np.full(3200, 0.2, dtype=np.float32)
        fake_mod = _fake_sherpa_module(wave, 16000)
        with tempfile.TemporaryDirectory() as tmp:
            bundle = _create_dummy_matcha_bundle(Path(tmp) / "zh-tw-custom")
            cfg = Config()
            cfg.tts.type = "matcha"
            cfg.tts.model = str(bundle)
            parent = _DummyParent()
            with patch.dict(sys.modules, {"sherpa_onnx": fake_mod}):
                engine = MatchaTTS(cfg, parent)
                fragment = PlayableFragment(
                    envelope=TurnEnvelope(turn_id="t", generation=1, stage="tts", sequence=0),
                    text="測試",
                    estimated_seconds=0.5,
                )
                # Cancel after first 2 chunks
                engine.synthesize_fragment(fragment, chunk_guard=lambda seq: seq < 2)
        self.assertEqual(len(parent.frames), 2)

    def test_empty_audio_reports_fragment_failure(self):
        fake_mod = _fake_sherpa_module(np.empty(0, dtype=np.float32), 16000)
        with tempfile.TemporaryDirectory() as tmp:
            bundle = _create_dummy_matcha_bundle(Path(tmp) / "zh-tw-custom")
            cfg = Config()
            cfg.tts.type = "matcha"
            cfg.tts.model = str(bundle)
            parent = _DummyParent()
            with patch.dict(sys.modules, {"sherpa_onnx": fake_mod}):
                engine = MatchaTTS(cfg, parent)
                engine.txt_to_audio(("...", {"turn_id": "turn-empty", "generation": 1, "fragment_sequence": 0}))
        self.assertEqual(len(parent.frames), 0)
        self.assertEqual(len(parent.failures), 1)
        self.assertEqual(parent.failures[0][1], "tts_empty_audio")

    def test_peak_headroom_prevents_clipping_and_int16_wraparound(self):
        from src.avatars.base import BaseAvatar

        # Loud >1.0 input must be normalized below 0.88 by MatchaTTS
        overdriven = np.full(3200, 1.45, dtype=np.float32)
        fake_mod = _fake_sherpa_module(overdriven, 16000)
        with tempfile.TemporaryDirectory() as tmp:
            bundle = _create_dummy_matcha_bundle(Path(tmp) / "zh-tw-custom")
            cfg = Config()
            cfg.tts.type = "matcha"
            cfg.tts.model = str(bundle)
            parent = _DummyParent()
            with patch.dict(sys.modules, {"sherpa_onnx": fake_mod}):
                engine = MatchaTTS(cfg, parent)
                samples, _ = engine._synthesize_samples("測試峰值保護")
        self.assertLessEqual(float(np.max(np.abs(samples))), 0.8801)

        # Direct audio conversion in BaseAvatar must clip before int16 cast (never wrap negative)
        captured: list[bytes] = []

        class _FakeTrack:
            def prepare_speech_start(self):
                return None

        avatar = BaseAvatar.__new__(BaseAvatar)
        avatar._direct_audio_track = _FakeTrack()
        avatar._direct_audio_loop = object()
        avatar._direct_audio_quit = None
        avatar.recording = False

        with patch("src.avatars.base.wait_media_coroutine", return_value=True), patch(
            "src.avatars.base.enqueue_media_frame",
            side_effect=lambda _t, frame, *_a: captured.append(bytes(frame.planes[0])) or True,
        ):
            ok = avatar._enqueue_direct_audio(np.full(320, 1.5, dtype=np.float32), {"status": "start"})
        self.assertTrue(ok)
        pcm = np.frombuffer(captured[0], dtype=np.int16)
        self.assertTrue(np.all(pcm == 32767))


class MatchaRuntimeSettingsTests(unittest.TestCase):
    def test_matcha_allows_bilingual_conversation_and_runtime_apply(self):
        cfg = Config()
        cfg.asr.type = "whisper"
        cfg.tts.type = "matcha"
        check_language_support(cfg, "zh-TW")
        check_language_support(cfg, "en-US")

        snap = speech_snapshot(cfg)["tts"]
        self.assertIn("models_by_engine", snap)

        with tempfile.TemporaryDirectory() as tmp:
            bundle = _create_dummy_matcha_bundle(Path(tmp) / "zh-tw-custom")
            with patch("src.server.runtime_settings._engine_available", return_value=True), patch(
                "src.server.runtime_settings._preview_tts",
                return_value="data:audio/wav;base64,dGVzdA==",
            ), patch("src.server.runtime_settings.persist_runtime_overrides"):
                result = apply_tts_settings(
                    cfg,
                    {
                        "type": "matcha",
                        "model": str(bundle),
                        "num_threads": 4,
                        "length_scale": 0.95,
                    },
                    session_count=0,
                )
        self.assertEqual(cfg.tts.type, "matcha")
        self.assertEqual(cfg.tts.device, "cpu")
        self.assertEqual(cfg.tts.num_threads, 4)
        self.assertAlmostEqual(cfg.tts.length_scale, 0.95)
        self.assertEqual(result["type"], "matcha")

    def test_apply_matcha_rejects_invalid_length_scale(self):
        cfg = Config()
        with patch("src.server.runtime_settings._engine_available", return_value=True):
            with self.assertRaises(SettingsError):
                apply_tts_settings(
                    cfg,
                    {"type": "matcha", "length_scale": 5.0},
                    session_count=0,
                )


@pytest.mark.live
def test_live_matcha_cpu_synthesis():
    repo_root = Path(__file__).resolve().parents[1]
    base_dir = repo_root / "models/tts/matcha-icefall-zh-en"
    if not base_dir.is_dir():
        pytest.skip("Baseline Matcha ONNX directory not present")
    cfg = Config()
    cfg.tts.type = "matcha"
    cfg.tts.model = str(base_dir)
    cfg.tts.num_threads = 4
    parent = _DummyParent()
    engine = create_tts_engine("matcha", cfg, parent)
    engine.txt_to_audio(("繁體中文測試，歡迎使用數位分身系統。", {"smoke": True}))
    assert len(parent.frames) > 10
