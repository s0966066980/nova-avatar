# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

import http.server
import json
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import soundfile as sf

from scripts import tts_bakeoff
from scripts.tts_bakeoff import (
    DEFAULT_SENTENCES,
    NvidiaSmi,
    Sentence,
    VramSampler,
    ZeroShotClient,
    duration_flags,
    fragment_length,
    load_sentence_sets,
    score_transcript,
    scoring_tokens,
    summarize_soak,
)


class SentenceSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sets = load_sentence_sets(DEFAULT_SENTENCES)

    def test_first_fragments_are_about_fifteen_characters(self):
        fragments = self.sets.first_fragments
        self.assertGreaterEqual(len(fragments), 10)
        lengths = [fragment_length(item.text) for item in fragments]
        self.assertTrue(all(10 <= length <= 18 for length in lengths), lengths)
        self.assertAlmostEqual(sum(lengths) / len(lengths), 15, delta=2)

    def test_zh_tw_set_has_one_hundred_sentences_with_unique_ids(self):
        zh = self.sets.corpus("zh-TW")
        self.assertEqual(len(zh), 100)
        ids = [item.sentence_id for item in self.sets.all_items()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_zh_tw_set_covers_taiwan_readings_places_money_dates_and_code_switching(self):
        zh = self.sets.corpus("zh-TW")
        by_category = {}
        for item in zh:
            by_category.setdefault(item.category, []).append(item)
        readings = " ".join(item.text for item in by_category["taiwan-reading"])
        for word in ("垃圾", "和", "星期", "企業"):
            self.assertIn(word, readings)
        self.assertGreaterEqual(len(by_category["place-name"]), 15)
        self.assertGreaterEqual(len(by_category["zh-en"]), 15)
        numbers = by_category["number"]
        self.assertTrue(any("NT$" in item.text for item in numbers))
        self.assertTrue(any("新台幣" in item.text for item in numbers))
        self.assertTrue(any(re.search(r"\d+年\d+月\d+日", item.text) for item in numbers))
        # Written digits need a spoken alternative so ASR numerals in either form score fairly.
        self.assertTrue(all(item.alternatives for item in numbers if re.search(r"\d", item.text)))
        self.assertTrue(all(re.search(r"[A-Za-z]", item.text) for item in by_category["zh-en"]))

    def test_focus_words_appear_in_their_sentences(self):
        for item in self.sets.all_items():
            for word in item.focus:
                self.assertIn(word, item.text, item.sentence_id)

    def test_english_set_is_english(self):
        en = self.sets.corpus("en-US")
        self.assertGreaterEqual(len(en), 30)
        self.assertTrue(all(not re.search(r"[㐀-鿿]", item.text) for item in en))


ZH_ITEM = Sentence("tw-reading-01", "zh-TW", "taiwan-reading", "請把垃圾丟進分類回收桶。", ("垃圾",))
MONEY = Sentence("number-02", "zh-TW", "number", "這台筆電售價新台幣32,900元。",
                 alternatives=("這台筆電售價新台幣三萬兩千九百元。",))


class ScoringTests(unittest.TestCase):
    def test_spoken_and_written_numbers_score_alike(self):
        self.assertEqual(scoring_tokens("新台幣三萬兩千九百元"), scoring_tokens("新台幣32,900元"))
        self.assertEqual(scoring_tokens("二零二六年十月三十日"), scoring_tokens("2026年10月30日"))
        self.assertEqual(scoring_tokens("一百五十萬元"), scoring_tokens("150萬元"))
        # Whisper mixes the two forms.
        self.assertEqual(scoring_tokens("新台幣3萬2千9百元"), scoring_tokens("新台幣32,900元"))
        self.assertEqual(scoring_tokens("一千零五"), scoring_tokens("1005"))
        self.assertEqual(scoring_tokens("下午兩點三十分"), scoring_tokens("下午2點30分"))

    def test_the_closest_accepted_transcript_is_scored(self):
        written = score_transcript(MONEY, "這台筆電售價新台幣32900元")
        spoken = score_transcript(MONEY, "这台笔电售价新台币三万两千九百元")
        self.assertEqual((written["edits"], spoken["edits"]), (0, 0))
        wrong = score_transcript(ZH_ITEM, "請把拉機丟進分類回收桶")
        self.assertEqual((wrong["edits"], wrong["reference_tokens"]), (2, 11))
        self.assertEqual(wrong["flags"], [])

    def test_missing_ending_is_truncation(self):
        self.assertEqual(score_transcript(ZH_ITEM, "請把垃圾丟進分類")["flags"], ["truncated"])

    def test_extra_or_repeated_speech_is_hallucination(self):
        repeated = score_transcript(ZH_ITEM, "請把垃圾丟進分類回收桶回收桶回收桶回收桶")
        self.assertEqual(repeated["flags"], ["hallucinated"])
        extra = score_transcript(ZH_ITEM, "請把垃圾丟進分類回收桶然後我們去吃晚餐好嗎")
        self.assertEqual(extra["flags"], ["hallucinated"])


class DurationFlagTests(unittest.TestCase):
    RATE = 16000

    def tone(self, seconds):
        return (np.sin(np.arange(int(seconds * self.RATE))) * 8000).astype(np.int16)

    def test_plausible_audio_has_no_flags(self):
        self.assertEqual(duration_flags(ZH_ITEM, self.tone(2.5), self.RATE), [])

    def test_silent_or_missing_audio_is_empty(self):
        self.assertEqual(duration_flags(ZH_ITEM, np.zeros(self.RATE * 2, np.int16), self.RATE), ["empty"])
        self.assertEqual(duration_flags(ZH_ITEM, np.zeros(0, np.int16), self.RATE), ["empty"])

    def test_audio_far_too_short_or_long_for_the_text(self):
        # 11 characters: plausible between about 1.1 s and 8 s.
        self.assertEqual(duration_flags(ZH_ITEM, self.tone(0.6), self.RATE), ["too_short"])
        self.assertEqual(duration_flags(ZH_ITEM, self.tone(12), self.RATE), ["too_long"])


class VramTests(unittest.TestCase):
    def test_reads_gpu_and_process_memory_from_nvidia_smi(self):
        outputs = {"--query-gpu=memory.used": "22197\n",
                   "--query-compute-apps=pid,used_memory": "1234, 3000\n5678, 6000\n"}

        def runner(command):
            return next(value for key, value in outputs.items() if key in command)

        probe = NvidiaSmi(runner=runner)
        self.assertEqual(probe.gpu_used_mib(), 22197)
        self.assertEqual(probe.process_used_mib(5678), 6000)
        self.assertIsNone(probe.process_used_mib(42))

    def test_sampler_reports_peak_delta_over_the_pre_launch_baseline(self):
        probe = Mock()
        probe.gpu_used_mib.side_effect = [20000, 22500, 22100]
        probe.process_used_mib.side_effect = [2400, 2600, 2500]
        sampler = VramSampler(probe, server_pid=99, baseline_mib=19800)
        for _ in range(3):
            sampler.sample()

        self.assertEqual(sampler.summary(), {
            "baseline_mib": 19800, "first_sample_mib": 20000, "peak_mib": 22500,
            "delta_peak_mib": 2700, "server_pid": 99, "server_process_peak_mib": 2600,
            "samples": 3, "errors": []})

    def test_missing_nvidia_smi_is_recorded_not_fatal(self):
        def runner(command):
            raise FileNotFoundError("nvidia-smi")

        sampler = VramSampler(NvidiaSmi(runner=runner), server_pid=None, baseline_mib=None)
        sampler.sample()
        summary = sampler.summary()
        self.assertIsNone(summary["peak_mib"])
        self.assertIsNone(summary["delta_peak_mib"])
        self.assertIn("nvidia-smi", summary["errors"][0])


class FakeTTSServer:
    """A loopback server speaking the owned zero-shot contract."""

    def __init__(self, *, family="breezyvoice", sample_rate=22050, chunks=(b"\x01\x00" * 100,),
                 delays=(0.0,), status=200):
        self.family, self.sample_rate, self.status = family, sample_rate, status
        self.chunks, self.delays = list(chunks), list(delays)
        self.bodies: list[bytes] = []
        self.llm_requests = 0
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            disable_nagle_algorithm = True

            def log_message(self, *args):
                pass

            def do_GET(self):
                body = json.dumps({"status": "ok", "sample_rate": fake.sample_rate,
                                   "family": fake.family}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                if self.path.endswith("/chat/completions"):
                    fake.llm_requests += 1
                    events = b"".join(
                        b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n' for _ in range(3))
                    events += b"data: [DONE]\n\n"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Content-Length", str(len(events)))
                    self.end_headers()
                    self.wfile.write(events)
                    return
                fake.bodies.append(body)
                if fake.status != 200:
                    body = b'{"detail":"model failed"}'
                    self.send_response(fake.status)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(200)
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                for index, chunk in enumerate(fake.chunks):
                    time.sleep(fake.delays[index] if index < len(fake.delays) else 0.0)
                    self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


class ZeroShotClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.prompt = Path(self.tmp.name) / "prompt.wav"
        self.prompt.write_bytes(b"RIFF-prompt-bytes")

    def tearDown(self):
        self.tmp.cleanup()

    def test_times_first_audio_and_whole_fragment_and_decodes_pcm(self):
        chunks = (np.full(2205, 1000, np.int16).tobytes(), np.full(2205, -1000, np.int16).tobytes())
        with FakeTTSServer(chunks=chunks, delays=(0.05, 0.1)) as server:
            client = ZeroShotClient(server.url, self.prompt, "參考逐字稿")
            self.assertEqual(client.health()["family"], "breezyvoice")
            result = client.synthesize("歡迎來到臺北。", "zh-TW")

        self.assertTrue(result.ok)
        self.assertGreaterEqual(result.first_audio_seconds, 0.05)
        self.assertGreaterEqual(result.total_seconds, result.first_audio_seconds + 0.09)
        self.assertEqual(result.sample_rate, 22050)
        self.assertEqual(result.samples.size, 4410)
        self.assertAlmostEqual(result.audio_seconds, 0.2)
        body = server.bodies[0]
        self.assertIn("歡迎來到臺北。".encode(), body)
        self.assertIn("參考逐字稿".encode(), body)
        self.assertIn(b'name="language"', body)
        self.assertIn(b"Chinese", body)
        self.assertIn(b"RIFF-prompt-bytes", body)

    def test_cosyvoice3_gets_the_same_prompt_prefix_the_app_sends(self):
        with FakeTTSServer(family="cosyvoice3", sample_rate=24000) as server:
            client = ZeroShotClient(server.url, self.prompt, "參考逐字稿")
            client.health()
            client.synthesize("Hello.", "en-US")
        self.assertIn("You are a helpful assistant.<|endofprompt|>參考逐字稿".encode(), server.bodies[0])
        self.assertIn(b"English", server.bodies[0])

    def test_http_errors_are_recorded_not_raised(self):
        with FakeTTSServer(status=400) as server:
            client = ZeroShotClient(server.url, self.prompt, "")
            client.health()
            result = client.synthesize("你好。", "zh-TW")
        self.assertFalse(result.ok)
        self.assertIn("400", result.error)
        self.assertEqual(result.samples.size, 0)


SMALL_SET = {
    "first_fragments": [{"id": "fragment-01", "text": "歡迎來到臺北，我是你的數位助理。"},
                        {"id": "fragment-02", "text": "好的，我馬上幫您查詢相關資料。"}],
    "zh-TW": [{"id": "tw-01", "category": "taiwan-reading", "text": "請把垃圾丟進回收桶<b>。",
               "focus": ["垃圾"]},
              {"id": "place-01", "category": "place-name", "text": "我們從基隆到新竹。"}],
    "en-US": [{"id": "en-01", "category": "english", "text": "Welcome to Taipei."}],
}


class BakeoffPipelineTests(unittest.TestCase):
    """run -> score -> report against a fake engine, as the live steps run them."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sentences = self.root / "sentences.json"
        self.sentences.write_text(json.dumps(SMALL_SET, ensure_ascii=False), encoding="utf-8")
        self.prompt = self.root / "prompt.wav"
        self.prompt.write_bytes(b"RIFF")
        self.run_dir = self.root / "runs" / "fake"

    def tearDown(self):
        self.tmp.cleanup()

    def run_engine(self, server, *extra):
        tone = (np.sin(np.arange(16000) / 3) * 8000).astype(np.int16).tobytes()
        server.chunks = [tone]
        return tts_bakeoff.main([
            "run", "--engine", "fake", "--url", server.url, "--prompt-wav", str(self.prompt),
            "--prompt-text", "參考", "--sentences", str(self.sentences), "--out-dir", str(self.run_dir),
            "--cold-rounds", "2", "--idle-seconds", "0", "--warmup", "1", "--warm-rounds", "1",
            "--stability-count", "6", "--nvidia-smi", str(self.root / "no-nvidia-smi"), *extra])

    def test_run_records_latency_phases_vram_and_saves_audio(self):
        with FakeTTSServer(sample_rate=16000) as server:
            self.assertEqual(self.run_engine(server, "--llm-url", f"{server.url}/v1"), 0)
            llm_requests = server.llm_requests

        run = json.loads((self.run_dir / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(run["server"]["sample_rate"], 16000)
        self.assertEqual([len(run["latency"][phase]) for phase in ("cold", "warm", "contended")], [2, 2, 2])
        self.assertTrue(run["latency"]["cold"][0]["first_after_load"])
        self.assertGreater(run["llm_load"]["chunks"], 0)
        self.assertGreater(llm_requests, 0)
        self.assertIn("errors", run["vram"])
        utterances = run["utterances"]
        self.assertEqual(len(utterances), 6)  # 3 corpus sentences, repeated to the stability count
        self.assertEqual([row["round"] for row in utterances], [1, 1, 1, 2, 2, 2])
        for row in utterances:
            samples, rate = sf.read(self.run_dir / row["audio"], dtype="int16")
            self.assertEqual((samples.size, rate), (16000, 16000))
            self.assertEqual(row["duration_flags"], [])
        self.assertTrue((self.run_dir / "audio" / "fragments" / "fragment-01.wav").is_file())

    def test_score_and_report_build_rates_and_an_escaped_listening_page(self):
        with FakeTTSServer(sample_rate=16000) as server:
            self.run_engine(server)
        heard = {"tw-01": "請把垃圾丟進回收桶<b>。", "place-01": "我們從基隆到新竹", "en-01": "Welcome to Taipei"}

        def recognize(path: Path, language: str) -> str:
            text = heard[path.stem]
            # Round 2 of the first sentence stops early.
            return text[:4] if path.parent.name == "r2" and path.stem == "tw-01" else text

        tts_bakeoff.score_run(self.run_dir, recognize, settings={"model": "fake"})
        report = tts_bakeoff.build_report([self.run_dir])
        engine = report["engines"]["fake"]
        self.assertEqual(engine["accuracy"]["zh-TW"]["error_rate"], 0.0)
        self.assertEqual(engine["accuracy"]["en-US"]["error_rate"], 0.0)
        self.assertEqual(engine["stability"]["utterances"], 6)
        self.assertEqual(engine["stability"]["truncated"], 1)
        self.assertAlmostEqual(engine["stability"]["any_issue_rate"], 1 / 6, places=3)
        warm = engine["latency"]["warm"]
        self.assertEqual(warm["n"], 2)
        self.assertLess(warm["first_audio_p50"], 0.4)
        self.assertTrue(engine["meets_target"]["warm"])

        out = self.root / "report"
        self.assertEqual(tts_bakeoff.main(["report", "--runs", str(self.run_dir), "--output-dir", str(out)]), 0)
        page = (out / "index.html").read_text(encoding="utf-8")
        self.assertIn('src="../runs/fake/audio/r1/tw-01.wav"', page)
        self.assertIn("回收桶&lt;b&gt;", page)
        self.assertNotIn("回收桶<b>", page)
        self.assertTrue((out / "bakeoff.json").is_file())

    def test_soak_streams_json_lines_and_summarizes_on_exit(self):
        out = self.run_dir / "soak.jsonl"
        with FakeTTSServer(sample_rate=16000) as server:
            server.chunks = [(np.sin(np.arange(16000) / 3) * 8000).astype(np.int16).tobytes()]
            code = tts_bakeoff.main([
                "soak", "--engine", "fake", "--url", server.url, "--prompt-wav", str(self.prompt),
                "--prompt-text", "參考", "--sentences", str(self.sentences), "--hours", "0.0001",
                "--interval", "0", "--vram-every", "0", "--output", str(out),
                "--nvidia-smi", str(self.root / "no-nvidia-smi")])
        self.assertEqual(code, 0)
        rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(any(row["type"] == "synthesis" and row["ok"] for row in rows))
        summary = json.loads((self.run_dir / "soak-summary.json").read_text(encoding="utf-8"))
        self.assertGreater(summary["requests"], 0)
        self.assertEqual(summary["failures"], 0)


class SoakSummaryTests(unittest.TestCase):
    def test_hourly_latency_drift_failures_and_vram_growth(self):
        rows = []
        for hour, latency in enumerate((0.30, 0.35, 0.50)):
            for minute in range(3):
                rows.append({"type": "synthesis", "t": hour * 3600 + minute * 60, "ok": True,
                             "first_audio_seconds": latency, "total_seconds": latency + 0.1,
                             "audio_seconds": 2.0, "flags": []})
            rows.append({"type": "vram", "t": hour * 3600, "gpu_mib": 20000 + 100 * hour,
                         "process_mib": 3000 + 100 * hour})
        rows.append({"type": "synthesis", "t": 7300, "ok": False, "error": "HTTP 500",
                     "first_audio_seconds": None, "total_seconds": 1.0, "audio_seconds": 0.0, "flags": []})
        rows.append({"type": "synthesis", "t": 7400, "ok": True, "first_audio_seconds": 0.5,
                     "total_seconds": 0.6, "audio_seconds": 0.0, "flags": ["empty"]})

        summary = summarize_soak(rows)

        self.assertEqual(summary["requests"], 11)
        self.assertEqual(summary["failures"], 1)
        self.assertEqual(summary["flags"], {"empty": 1})
        self.assertEqual([bucket["first_audio_p50"] for bucket in summary["hourly"]], [0.3, 0.35, 0.5])
        self.assertAlmostEqual(summary["latency_drift_p50_seconds"], 0.2)
        self.assertAlmostEqual(summary["vram"]["gpu_growth_mib_per_hour"], 100.0)
        self.assertAlmostEqual(summary["vram"]["process_growth_mib_per_hour"], 100.0)
        self.assertEqual(summary["vram"]["gpu_max_mib"], 20200)
