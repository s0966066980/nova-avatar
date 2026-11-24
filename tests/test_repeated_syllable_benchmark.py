# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The repeated-syllable benchmark, driven through fake synthesiser and transcriber."""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/tts-bench/repeated_syllables.py"
SPEC = importlib.util.spec_from_file_location("repeated_syllables", SCRIPT)
bench = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(bench)


class RepeatedTokenRuleTests(unittest.TestCase):
    # Literals come from the 2026-11-24 diagnosis (asr_out.json), not from the rule.
    def test_doubled_syllables_missing_from_the_reference_are_flagged(self):
        found = bench.repeated_tokens("這瓶液體不能帶上飛機。", "這瓶液液體體不能帶上飛機")
        self.assertEqual(found, ["体", "液"])

    def test_a_faithful_transcript_is_not_flagged(self):
        self.assertEqual(bench.repeated_tokens("這瓶液體不能帶上飛機。", "這瓶液體不能帶上飛機。"), [])

    def test_a_repeat_the_reference_itself_contains_is_not_flagged(self):
        self.assertEqual(bench.repeated_tokens("謝謝你，天天開心", "謝謝你天天開心"), [])

    def test_repeated_digits_and_latin_letters_are_ignored(self):
        self.assertEqual(bench.repeated_tokens("預購到2027年", "預購到2027年 oo 22"), [])

    def test_script_and_punctuation_differences_are_not_repeats(self):
        self.assertEqual(bench.repeated_tokens("臺灣，很美！", "台湾很美"), [])


SAMPLE_RATE = 16000


class ScriptedVoice:
    """Fake synthesiser and transcriber: each synthesis is heard as the next scripted transcript."""

    def __init__(self, heard):
        self.heard = list(heard)
        self.spoken = []

    def synthesise(self, text):
        self.spoken.append(text)
        return np.zeros(SAMPLE_RATE * len(self.spoken), dtype=np.float32)

    def transcribe(self, samples):
        return self.heard.pop(0)


def said(text, words=()):
    return bench.Transcript(text=text, words=[tuple(word) for word in words])


SETS = {
    "repeat_prone": [{"id": "liquid", "text": "這瓶液體不能帶上飛機。"}],
    "clean": [{"id": "bank", "text": "銀行在這條街的轉角。"}, {"id": "book", "text": "我還沒有把書還給圖書館。"}],
}


class RunBenchmarkTests(unittest.TestCase):
    def run_scripted(self, heard, repeats):
        voice = ScriptedVoice(heard)
        report = bench.run_benchmark(voice.synthesise, voice.transcribe, SETS, repeats)
        return voice, report

    def test_every_sentence_is_synthesised_once_per_repeat_and_the_sets_are_counted(self):
        heard = [
            said("這瓶液液體體不能帶上飛機", [("液", 0.4, 0.6), ("液", 0.6, 0.78)]),
            said("這瓶液體不能帶上飛機"),
            said("銀行在這條街的轉角"), said("銀行在這條街的轉角"),
            said("我還還沒有把書還給圖書館"), said("我還沒有把書還給圖書館"),
        ]
        voice, report = self.run_scripted(heard, repeats=2)
        self.assertEqual(len(voice.spoken), 6)
        self.assertEqual(report["sets"]["repeat_prone"]["flagged_runs"], 1)
        self.assertEqual(report["sets"]["repeat_prone"]["total_runs"], 2)
        self.assertEqual(report["sets"]["clean"]["flagged_runs"], 1)
        self.assertEqual(report["sets"]["clean"]["total_runs"], 4)

    def test_a_sentence_reports_its_runs_flagged_runs_repeated_tokens_and_durations(self):
        heard = [said("這瓶液液體體不能帶上飛機", [("液", 0.4, 0.6), ("液", 0.6, 0.78), ("體", 0.78, 0.94)]),
                 said("這瓶液體不能帶上飛機")]
        _, report = self.run_scripted(heard + [said("銀行在這條街的轉角")] * 2 + [said("我還沒有把書還給圖書館")] * 2, 2)
        sentence = report["sets"]["repeat_prone"]["sentences"][0]
        self.assertEqual(sentence["id"], "liquid")
        self.assertEqual(sentence["text"], "這瓶液體不能帶上飛機。")
        self.assertEqual(sentence["flagged_runs"], 1)
        self.assertEqual(sentence["repeated_tokens"], ["体", "液"])
        self.assertEqual(sentence["durations"], [1.0, 2.0])
        first, second = sentence["runs"]
        self.assertEqual(first["hypothesis"], "這瓶液液體體不能帶上飛機")
        self.assertEqual(first["repeated_tokens"], ["体", "液"])
        self.assertTrue(first["flagged"])
        self.assertFalse(second["flagged"])
        self.assertEqual(first["words"], [["液", 0.4, 0.6], ["液", 0.6, 0.78], ["體", 0.78, 0.94]])


class SentenceSetTests(unittest.TestCase):
    def test_the_committed_sets_hold_twelve_repeat_prone_and_twelve_clean_sentences(self):
        sets = bench.load_sentences()
        self.assertEqual(set(sets), {"repeat_prone", "clean"})
        self.assertEqual(len(sets["repeat_prone"]), 12)
        self.assertEqual(len(sets["clean"]), 12)
        ids = [sentence["id"] for group in sets.values() for sentence in group]
        self.assertEqual(len(ids), len(set(ids)))

    def test_the_sets_keep_the_diagnosis_sentences(self):
        sets = bench.load_sentences()
        self.assertIn("這瓶液體不能帶上飛機。", [s["text"] for s in sets["repeat_prone"]])
        self.assertIn("銀行在這條街的轉角。", [s["text"] for s in sets["clean"]])


class ModelDirectoryTests(unittest.TestCase):
    def make_directory(self, *names):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        directory = Path(scratch.name)
        for name in names:
            (directory / name).write_bytes(name.encode())
        return directory

    def test_a_voice_model_directory_resolves_model_onnx_without_a_voice_label(self):
        directory = self.make_directory("model.onnx", "vocos-16khz-univ.onnx", "lexicon.txt", "tokens.txt", "date-zh.fst")
        files = bench.locate_model_files(directory)
        self.assertEqual(files.acoustic_model, directory / "model.onnx")
        self.assertEqual(files.rule_fsts, (directory / "date-zh.fst",))

    def test_the_base_model_directory_resolves_its_steps_checkpoint(self):
        directory = self.make_directory("model-steps-3.onnx", "vocos-16khz-univ.onnx", "lexicon.txt", "tokens.txt")
        self.assertEqual(bench.locate_model_files(directory).acoustic_model, directory / "model-steps-3.onnx")

    def test_a_missing_file_fails_naming_it(self):
        directory = self.make_directory("model.onnx", "lexicon.txt", "tokens.txt")
        with self.assertRaisesRegex(bench.BenchmarkError, "vocos-16khz-univ.onnx"):
            bench.locate_model_files(directory)

    def test_a_directory_without_an_acoustic_model_fails(self):
        directory = self.make_directory("vocos-16khz-univ.onnx", "lexicon.txt", "tokens.txt")
        with self.assertRaisesRegex(bench.BenchmarkError, "model.onnx"):
            bench.locate_model_files(directory)

    def test_sha256_is_that_of_the_acoustic_model_file(self):
        directory = self.make_directory("model.onnx")
        self.assertEqual(bench.file_sha256(directory / "model.onnx"), hashlib.sha256(b"model.onnx").hexdigest())


class SummaryLineTests(unittest.TestCase):
    def test_one_line_gives_the_directory_the_hash_and_both_sets_as_flagged_over_total(self):
        report = {"sets": {"repeat_prone": {"flagged_runs": 17, "total_runs": 36},
                           "clean": {"flagged_runs": 2, "total_runs": 36}}}
        line = bench.summary_line(Path("/models/tts/zh-tw-hsiaochen-edge"), "ab12", report)
        self.assertEqual(
            line,
            "model=/models/tts/zh-tw-hsiaochen-edge sha256=ab12 repeat-prone=17/36 clean=2/36",
        )


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.model_dir = self.root / "voice"
        self.model_dir.mkdir()
        for name in ("model.onnx", "vocos-16khz-univ.onnx", "lexicon.txt", "tokens.txt"):
            (self.model_dir / name).write_bytes(name.encode())
        self.output = self.root / "result.json"
        self.synthesiser_files = []
        self.whisper_models = []
        # main() hides the GPU for the whole process; do not leak that into other tests.
        environment = mock.patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)

    def make_synthesiser(self, files):
        self.synthesiser_files.append(files)
        return lambda text: np.zeros(SAMPLE_RATE, dtype=np.float32)

    def make_transcriber(self, whisper_model):
        self.whisper_models.append(whisper_model)
        return lambda samples: said("這瓶液液體體不能帶上飛機")

    def run_main(self, *extra, model_dir=None):
        argv = [str(model_dir or self.model_dir), "--output", str(self.output), *extra]
        return bench.main(argv, make_synthesiser=self.make_synthesiser, make_transcriber=self.make_transcriber)

    def test_it_writes_the_report_and_prints_one_summary_line(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(self.run_main("--repeats", "2", "--whisper-model", "fake-whisper"), 0)
        report = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(report["model_dir"], str(self.model_dir))
        self.assertEqual(report["acoustic_model_sha256"], hashlib.sha256(b"model.onnx").hexdigest())
        self.assertEqual(report["whisper_model"], "fake-whisper")
        self.assertEqual(report["repeats"], 2)
        self.assertEqual(report["sets"]["repeat_prone"]["total_runs"], 24)
        self.assertEqual(self.whisper_models, ["fake-whisper"])
        lines = stdout.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(
            lines[0],
            f"model={self.model_dir} sha256={hashlib.sha256(b'model.onnx').hexdigest()} "
            "repeat-prone=24/24 clean=24/24",
        )

    def test_each_sentence_is_synthesised_three_times_by_default(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.run_main()
        report = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(report["repeats"], 3)
        self.assertEqual(report["sets"]["clean"]["total_runs"], 36)

    def test_the_gpu_is_hidden_before_any_model_is_made(self):
        seen = []
        with mock.patch.dict(os.environ, {"CUDA_VISIBLE_DEVICES": "0"}):
            with contextlib.redirect_stdout(io.StringIO()):
                bench.main(
                    [str(self.model_dir), "--output", str(self.output)],
                    make_synthesiser=lambda files: seen.append(os.environ["CUDA_VISIBLE_DEVICES"]) or (lambda text: np.zeros(1)),
                    make_transcriber=lambda model: seen.append(os.environ["CUDA_VISIBLE_DEVICES"]) or (lambda samples: said("")),
                )
        self.assertEqual(seen, ["", ""])

    def test_an_incomplete_model_directory_fails_with_a_message_and_writes_nothing(self):
        (self.model_dir / "tokens.txt").unlink()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(self.run_main(), 2)
        self.assertIn("tokens.txt", stderr.getvalue())
        self.assertFalse(self.output.exists())


class WhisperModelTests(unittest.TestCase):
    def test_a_missing_model_directory_fails_loudly_instead_of_skipping(self):
        with self.assertRaisesRegex(bench.BenchmarkError, "no/such/whisper"):
            bench.make_whisper_transcriber("/no/such/whisper")


if __name__ == "__main__":
    unittest.main()
