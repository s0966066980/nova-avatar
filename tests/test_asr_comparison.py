# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

import unittest
from unittest.mock import Mock

import numpy as np

from scripts.compare_asr import (
    build_report,
    error_counts,
    measure_engine,
    recognition_tokens,
    utterance_audio,
)
from src.server.reply_streaming.latency_baseline import LatencyFixture


ZH = LatencyFixture("general-zh-01", "general", "zh-TW", "請用一句話簡短介紹臺灣。")
EN = LatencyFixture("general-en-01", "general", "en-US", "What can you help me with today?")


class RecognitionTokenTests(unittest.TestCase):
    def test_chinese_is_scored_per_character_without_punctuation(self):
        self.assertEqual(recognition_tokens("你好，世界！"), ["你", "好", "世", "界"])

    def test_script_differences_are_not_recognition_errors(self):
        # Whisper may answer in simplified script; the subtitle script is a
        # separate concern reported as the raw error rate.
        self.assertEqual(recognition_tokens("台湾"), recognition_tokens("臺灣"))
        self.assertNotEqual(
            recognition_tokens("台湾", normalize_script=False),
            recognition_tokens("臺灣", normalize_script=False),
        )

    def test_english_is_scored_per_word_case_and_punctuation_insensitive(self):
        self.assertEqual(recognition_tokens("What's up, Taiwan?"), ["what's", "up", "taiwan"])

    def test_mixed_text_keeps_latin_words_whole(self):
        self.assertEqual(recognition_tokens("Nova Avatar 是什麼？", normalize_script=False),
                         ["nova", "avatar", "是", "什", "麼"])


class ErrorCountTests(unittest.TestCase):
    def test_counts_substitutions_insertions_and_deletions(self):
        self.assertEqual(error_counts("請問天氣", "請問天氣"), (0, 4))
        self.assertEqual(error_counts("請問天氣", "請文天氣"), (1, 4))
        self.assertEqual(error_counts("請問天氣", "請問"), (2, 4))
        self.assertEqual(error_counts("請問", "請問天氣"), (2, 2))
        self.assertEqual(error_counts("what can you do", "what you do now"), (2, 4))


class UtteranceAudioTests(unittest.TestCase):
    def test_trailing_silence_is_cut_to_the_vad_endpoint(self):
        voiced = (np.sin(np.arange(16000)) * 8000).astype(np.int16)
        samples = np.concatenate([np.zeros(3200, np.int16), voiced, np.zeros(14400, np.int16)])

        trimmed = utterance_audio(samples, sample_rate=16000, endpoint_silence_seconds=0.32)

        self.assertEqual(trimmed.size, 3200 + 16000 + 5120)


class MeasureEngineTests(unittest.TestCase):
    def test_each_round_times_one_recognition_in_the_fixture_language(self):
        engine = Mock(supports_language_options=True)
        engine.transcribe.side_effect = [
            {"text": "請用一句話簡短介紹台湾"},
            {"text": "What can you help me with today"},
        ] * 2
        ticks = iter([0.0, 0.2, 1.0, 1.1, 2.0, 2.3, 3.0, 3.1])
        audio = {ZH.fixture_id: b"zh-wav", EN.fixture_id: b"en-wav"}

        samples = measure_engine("whisper", engine, [ZH, EN], audio, rounds=2,
                                 clock=lambda: next(ticks))

        self.assertEqual(
            [call.args for call in engine.transcribe.call_args_list],
            [(b"zh-wav",), (b"en-wav",)] * 2)
        self.assertEqual(
            [call.kwargs for call in engine.transcribe.call_args_list],
            [{"language": "zh"}, {"language": "en"}] * 2)
        self.assertEqual([round(s["seconds"], 6) for s in samples], [0.2, 0.1, 0.3, 0.1])
        self.assertEqual([s["round"] for s in samples], [1, 1, 2, 2])
        first = samples[0]
        self.assertEqual((first["edits"], first["reference_tokens"]), (0, 11))
        self.assertEqual(first["raw_edits"], 2)  # 台/湾 vs 臺/灣

    def test_engines_without_language_options_get_audio_only(self):
        engine = Mock(supports_language_options=False)
        engine.transcribe.return_value = {"text": "請用一句話簡短介紹臺灣"}
        ticks = iter([0.0, 0.05])

        measure_engine("funasr", engine, [ZH], {ZH.fixture_id: b"wav"}, rounds=1,
                       clock=lambda: next(ticks))

        engine.transcribe.assert_called_once_with(b"wav")


class BuildReportTests(unittest.TestCase):
    def sample(self, engine, language, seconds, edits, tokens, raw_edits=None):
        return {"engine": engine, "fixture_id": f"{language}-x", "language": language,
                "round": 1, "seconds": seconds, "edits": edits, "reference_tokens": tokens,
                "raw_edits": edits if raw_edits is None else raw_edits,
                "reference": "", "hypothesis": ""}

    def test_reports_latency_percentiles_and_corpus_error_rate_per_language(self):
        samples = [
            self.sample("whisper", "zh-TW", 0.10, 1, 10, raw_edits=3),
            self.sample("whisper", "zh-TW", 0.20, 0, 10),
            self.sample("whisper", "zh-TW", 0.30, 1, 20),
            self.sample("whisper", "en-US", 0.40, 1, 5),
            self.sample("funasr", "zh-TW", 0.05, 0, 10),
            self.sample("funasr", "en-US", 0.06, 4, 5),
        ]

        report = build_report(samples, engines={"whisper": {"model": "small"},
                                                "funasr": {"model": "paraformer-zh"}},
                              environment={"device": "cuda"})

        zh = report["engines"]["whisper"]["languages"]["zh-TW"]
        self.assertEqual(zh["samples"], 3)
        self.assertEqual(zh["latency_seconds"], {"p50": 0.2, "p95": 0.29})
        self.assertAlmostEqual(zh["error_rate"], 2 / 40)
        self.assertAlmostEqual(zh["raw_error_rate"], 4 / 40)
        self.assertEqual(zh["metric"], "CER")
        self.assertEqual(report["engines"]["whisper"]["languages"]["en-US"]["metric"], "WER")
        self.assertEqual(report["engines"]["whisper"]["all"]["latency_seconds"]["p50"], 0.25)
        self.assertEqual(report["engines"]["whisper"]["settings"], {"model": "small"})
        # English sessions require Whisper (conversations.check_language_support).
        self.assertTrue(report["engines"]["whisper"]["languages"]["en-US"]["supported_in_app"])
        self.assertFalse(report["engines"]["funasr"]["languages"]["en-US"]["supported_in_app"])
        self.assertEqual(report["engines"]["funasr"]["all"]["samples"], 1)
        self.assertEqual(report["environment"], {"device": "cuda"})
        self.assertEqual(len(report["samples"]), 6)


if __name__ == "__main__":
    unittest.main()
