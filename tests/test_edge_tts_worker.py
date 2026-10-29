# Copyright (c) 2026 Kedreamix
# Modified by HongXian0903, 2026
# SPDX-License-Identifier: Apache-2.0

import asyncio
import time
import unittest
from io import BytesIO
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import numpy as np

from src.tts.base import State
from src.server.app import _await_edge_tts_prewarm, _start_edge_tts_prewarm


def _mp3_fixture() -> bytes:
    import av

    sample_rate = 24000
    tone_samples = int(sample_rate * 0.12)
    tone = (
        np.sin(2 * np.pi * 440 * np.arange(tone_samples) / sample_rate) * 8000
    ).astype(np.int16)
    output = BytesIO()
    with av.open(output, mode="w", format="mp3") as container:
        stream = container.add_stream("libmp3lame", rate=sample_rate)
        stream.layout = "mono"
        frame = av.AudioFrame.from_ndarray(
            tone.reshape(1, -1), format="s16", layout="mono"
        )
        frame.sample_rate = sample_rate
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    payload = output.getvalue()
    marker = payload.find(b"\xff\xf3")
    return payload[marker:] if marker >= 0 else payload


class EdgeTTSStartupTests(unittest.TestCase):
    @staticmethod
    def _config(engine: str = "edgetts"):
        return SimpleNamespace(
            tts=SimpleNamespace(
                type=engine,
                ref_file="zh-TW-YunJheNeural",
            )
        )

    def test_edge_prewarm_finishes_before_readiness(self):
        called = Event()

        with patch(
            "src.tts.engines.edge.prewarm_edge_tts",
            side_effect=lambda voice, **_kwargs: called.set() or True,
        ) as prewarm:
            worker = _start_edge_tts_prewarm(self._config())
            self.assertTrue(_await_edge_tts_prewarm(worker))

        self.assertTrue(called.is_set())
        prewarm.assert_called_once_with("zh-TW-YunJheNeural", decode_pcm=True, keep_connection=False)
        self.assertFalse(worker.is_alive())

    def test_non_edge_engine_does_not_start_edge_prewarm(self):
        with patch("src.tts.engines.edge.prewarm_edge_tts") as prewarm:
            worker = _start_edge_tts_prewarm(self._config("cosyvoice"))
            _await_edge_tts_prewarm(worker)

        self.assertIsNone(worker)
        prewarm.assert_not_called()

    def test_startup_prewarm_recovers_from_a_temporary_failure(self):
        with patch("src.tts.engines.edge.prewarm_edge_tts", side_effect=[False, True]) as prewarm, patch(
            "src.server.app.EDGE_PREWARM_RETRY_SECONDS", 0,
        ):
            self.assertTrue(_await_edge_tts_prewarm(_start_edge_tts_prewarm(self._config())))
        self.assertEqual(prewarm.call_count, 2)

    def test_startup_prewarm_stops_after_three_failures(self):
        with patch("src.tts.engines.edge.prewarm_edge_tts", return_value=False) as prewarm, patch(
            "src.server.app.EDGE_PREWARM_RETRY_SECONDS", 0,
        ):
            self.assertFalse(_await_edge_tts_prewarm(_start_edge_tts_prewarm(self._config())))
        self.assertEqual(prewarm.call_count, 3)


class EdgeTTSTransportTests(unittest.IsolatedAsyncioTestCase):
    async def _capture_prewarm_url(self, endpoint):
        from edge_tts import communicate
        from src.tts.engines.edge import _prewarm_edge_tts

        requests = []

        class ProbeComplete(Exception):
            pass

        class Session:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                pass

            def ws_connect(self, url, **_kwargs):
                requests.append(url)
                raise ProbeComplete

        with patch.object(communicate, "WSS_URL", endpoint), patch.object(
            communicate.aiohttp, "ClientSession", Session
        ):
            with self.assertRaises(ProbeComplete):
                await _prewarm_edge_tts("zh-TW-HsiaoChenNeural")
        return urlsplit(requests[0])

    async def test_prewarm_migrates_the_rejected_legacy_synthesis_endpoint(self):
        url = await self._capture_prewarm_url(
            "wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1"
            "?TrustedClientToken=test-public-client-token"
        )
        self.assertEqual(url.netloc, "api.msedgeservices.com")
        self.assertEqual(url.path, "/tts/cognitiveservices/websocket/v1")
        query = parse_qs(url.query)
        self.assertEqual(query["Ocp-Apim-Subscription-Key"], ["test-public-client-token"])
        self.assertNotIn("TrustedClientToken", query)
        self.assertIn("Sec-MS-GEC", query)
        self.assertIn("ConnectionId", query)

    async def test_prewarm_preserves_an_upstream_replacement_endpoint(self):
        url = await self._capture_prewarm_url("wss://future.example/synthesize?key=test")
        self.assertEqual(url.netloc, "future.example")
        self.assertEqual(url.path, "/synthesize")


class EdgeTTSWorkerTests(unittest.TestCase):
    def _make_tts(self, parent, **tts_fields):
        from src.tts.engines.edge import EdgeTTS

        fields = {
            "ref_file": "zh-TW-YunJheNeural",
            "edge_persistent_worker": True,
            "edge_prefetch": True,
        }
        fields.update(tts_fields)
        config = SimpleNamespace(
            audio=SimpleNamespace(fps=50),
            tts=SimpleNamespace(**fields),
        )
        tts = EdgeTTS(config, parent)
        self.addCleanup(tts.close_worker)
        return tts

    def test_prefetch_handoff_preserves_pcm_order_while_output_is_blocked(self):
        from src.tts.engines.edge import _GatedFrameSink

        blocked, resume = Event(), Event()
        received = []

        class Parent:
            def put_audio_frame(self, samples, eventpoint):
                received.append((int(samples[0]), eventpoint["media_sequence"]))
                if eventpoint["media_sequence"] == 0:
                    blocked.set()
                    resume.wait(timeout=2)

        sink = _GatedFrameSink(Parent())
        for sequence in (0, 1):
            sink.emit(np.full(320, sequence), {"media_sequence": sequence})
        releasing = Thread(target=sink.release)
        releasing.start()
        try:
            self.assertTrue(blocked.wait(timeout=1))
            # The decoder continues while release waits on the bounded WebRTC
            # queue. New PCM must stay behind the already buffered samples.
            sink.emit(np.full(320, 2), {"media_sequence": 2, "fragment_end": True})
        finally:
            resume.set()
            releasing.join(timeout=2)

        self.assertFalse(releasing.is_alive())
        self.assertEqual(received, [(0, 0), (1, 1), (2, 2)])

    def test_cancelling_prefetch_handoff_discards_unsent_pcm(self):
        from src.tts.engines.edge import _GatedFrameSink

        blocked, resume = Event(), Event()
        received = []

        class Parent:
            def put_audio_frame(self, _samples, eventpoint):
                received.append(eventpoint["media_sequence"])
                if eventpoint["media_sequence"] == 0:
                    blocked.set()
                    resume.wait(timeout=2)

        sink = _GatedFrameSink(Parent())
        for sequence in (0, 1):
            sink.emit(np.zeros(320), {"media_sequence": sequence})
        releasing = Thread(target=sink.release)
        releasing.start()
        try:
            self.assertTrue(blocked.wait(timeout=1))
            sink.cancel()
            sink.emit(np.zeros(320), {"media_sequence": 2})
        finally:
            resume.set()
            releasing.join(timeout=2)

        self.assertFalse(releasing.is_alive())
        self.assertEqual(received, [0])

    def test_rate_limited_synthesis_waits_before_retrying(self):
        from aiohttp import WSServerHandshakeError

        payload = _mp3_fixture()
        frames, failures, requests = [], [], []

        class Parent:
            def put_audio_frame(self, frame, _eventpoint):
                frames.append(frame)

            def notify_fragment_synthesis_failed(self, _eventpoint, reason):
                failures.append(reason)

        class RateLimitedCommunicate:
            async def stream(self):
                requests.append(time.monotonic())
                if len(requests) == 1 or requests[-1] - requests[0] < 0.95:
                    raise WSServerHandshakeError(
                        SimpleNamespace(real_url="https://example.invalid/tts"),
                        (), status=429, headers={"Retry-After": "1"},
                    )
                yield {"type": "audio", "data": payload}

        tts = self._make_tts(Parent())
        with patch(
            "src.tts.engines.edge.edge_tts.Communicate",
            side_effect=lambda *_args: RateLimitedCommunicate(),
        ):
            tts.txt_to_audio(("等待限流恢復。", {
                "turn_id": "turn-1", "generation": 1, "fragment_sequence": 0,
            }))

        self.assertEqual(failures, [])
        self.assertTrue(frames)
        self.assertEqual(len(requests), 2)
        self.assertGreaterEqual(requests[1] - requests[0], 0.95)

    def test_rate_limit_wait_can_be_cancelled_without_another_request(self):
        from aiohttp import WSServerHandshakeError

        waiting = Event()
        requests, failures = [], []

        class Parent:
            def notify_fragment_synthesis_failed(self, _eventpoint, reason):
                failures.append(reason)

        class RateLimitedCommunicate:
            async def stream(self):
                requests.append(1)
                raise WSServerHandshakeError(
                    SimpleNamespace(real_url="https://example.invalid/tts"),
                    # Fit the real two-second shared retry budget so this
                    # exercises cancellation during cooldown, not exhaustion.
                    (), status=429, headers={"Retry-After": "1"},
                )
                yield  # Make this a stream even though it fails before audio.

        tts = self._make_tts(Parent())
        wait_for_rate_limit = tts._wait_for_rate_limit

        async def observe_wait(max_wait_seconds):
            if tts._rate_limit_until > time.monotonic():
                waiting.set()
            return await wait_for_rate_limit(max_wait_seconds)

        worker = Thread(target=tts.txt_to_audio, args=(("取消等待。", {
            "turn_id": "turn-1", "generation": 1, "fragment_sequence": 0,
        }),))
        with patch(
            "src.tts.engines.edge.edge_tts.Communicate",
            side_effect=lambda *_args: RateLimitedCommunicate(),
        ), patch.object(tts, '_wait_for_rate_limit', side_effect=observe_wait):
            worker.start()
            try:
                self.assertTrue(waiting.wait(timeout=1))
                tts.flush_talk()
                worker.join(timeout=0.5)
                self.assertFalse(worker.is_alive())
            finally:
                tts.flush_talk()
                worker.join(timeout=1)

        self.assertEqual(requests, [1])
        self.assertEqual(failures, [])

    def test_rate_limit_does_not_exceed_the_shared_retry_budget(self):
        from aiohttp import WSServerHandshakeError
        from src.server.reply_streaming.channel import PlayableFragment
        from src.server.reply_streaming.retry import RetryBudget
        from src.server.reply_streaming.turn import TurnContext

        requests, failures = [], []

        class Parent:
            def notify_fragment_synthesis_failed(self, _eventpoint, reason):
                failures.append(reason)

        class RateLimitedCommunicate:
            async def stream(self):
                requests.append(1)
                raise WSServerHandshakeError(
                    SimpleNamespace(real_url="https://example.invalid/tts"),
                    (), status=429, headers={"Retry-After": "5"},
                )
                yield

        turn = TurnContext(turn_id="turn-1", generation=1)
        fragment = PlayableFragment(
            envelope=turn.envelope(stage="tts_fragment", sequence=0),
            text="不得超出等待預算。", estimated_seconds=0.5,
        )
        tts = self._make_tts(Parent())
        with patch(
            "src.tts.engines.edge.edge_tts.Communicate",
            side_effect=lambda *_args: RateLimitedCommunicate(),
        ):
            tts.synthesize_fragment(
                fragment, chunk_guard=lambda _sequence: True,
                retry_budget=RetryBudget(max_retries=1, extra_wait_seconds=0.1),
            )

        self.assertEqual(requests, [1])
        self.assertEqual(failures, ["tts_exhausted_before_audio"])

    def test_prefetched_first_reply_does_not_wait_past_its_retry_budget(self):
        from aiohttp import WSServerHandshakeError

        requests, failures = [], []

        class RateLimitedCommunicate:
            async def stream(self):
                requests.append(1)
                raise WSServerHandshakeError(
                    SimpleNamespace(real_url="https://example.invalid/tts"),
                    (), status=429, headers={"Retry-After": "5"},
                )
                yield

        parent = SimpleNamespace(
            notify_fragment_synthesis_failed=lambda _event, reason: failures.append(reason),
        )
        tts = self._make_tts(parent)
        job = None
        try:
            with patch(
                "src.tts.engines.edge.edge_tts.Communicate",
                side_effect=lambda *_args: RateLimitedCommunicate(),
            ):
                job = tts._launch_stream(("第一輪回覆。", {
                    "turn_id": "first", "generation": 0, "fragment_sequence": 0,
                }), gated=False)
                deadline = time.monotonic() + 0.3
                while time.monotonic() < deadline and not tts._finish_job(job):
                    pass
                self.assertEqual(failures, ["tts_exhausted_before_audio"])
                self.assertEqual(requests, [1])
        finally:
            tts._cancel_job(job)

    def test_prefetch_limits_requests_and_eventually_emits_all_fragments_in_order(self):
        from src.tts.engines.edge import EDGE_MAX_PREFETCH_JOBS

        payload = _mp3_fixture()
        release = Event()
        started = [Event() for _ in range(6)]
        emitted = []

        class Parent:
            def put_audio_frame(self, _frame, eventpoint):
                emitted.append(eventpoint["fragment_sequence"])

        class Communicate:
            def __init__(self, index):
                self.index = index

            async def stream(self):
                started[self.index].set()
                yield {"type": "audio", "data": payload}
                while not release.is_set():
                    await asyncio.sleep(0.01)

        tts = self._make_tts(Parent())
        for sequence in range(len(started)):
            tts.put_msg_txt(str(sequence), {
                "turn_id": "turn-1", "generation": 1,
                "fragment_sequence": sequence,
            })
        quit_event = Event()
        worker = Thread(target=tts.process_tts, args=(quit_event,))
        with patch(
            "src.tts.engines.edge.edge_tts.Communicate",
            side_effect=lambda text, _voice: Communicate(int(text)),
        ):
            worker.start()
            try:
                for index in range(EDGE_MAX_PREFETCH_JOBS + 1):
                    self.assertTrue(started[index].wait(timeout=1))
                self.assertFalse(started[EDGE_MAX_PREFETCH_JOBS + 1].wait(timeout=0.1))
                release.set()
                deadline = time.monotonic() + 2
                while len(set(emitted)) < len(started) and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(set(emitted), set(range(len(started))))
                self.assertEqual(emitted, sorted(emitted))
            finally:
                release.set()
                quit_event.set()
                worker.join(timeout=2)

        self.assertFalse(worker.is_alive())

    def test_persistent_worker_reuses_the_same_event_loop(self):
        payload = _mp3_fixture()

        class Parent:
            def put_audio_frame(self, _frame, _eventpoint):
                return None

        class WorkingCommunicate:
            async def stream(self):
                yield {"type": "audio", "data": payload}

        tts = self._make_tts(Parent())
        with patch(
            "src.tts.engines.edge.edge_tts.Communicate",
            side_effect=lambda *_args: WorkingCommunicate(),
        ):
            tts.txt_to_audio(("第一段。", {}))
            loop = tts.worker_loop
            tts.txt_to_audio(("第二段。", {}))

        self.assertIsNotNone(loop)
        self.assertIs(tts.worker_loop, loop)
        self.assertTrue(loop.is_running())

    def test_first_fragment_pcm_does_not_wait_for_the_next_edge_request(self):
        payload = _mp3_fixture()
        first_pcm = Event()
        second_started = Event()
        first_hold = Event()
        emitted = []

        class Parent:
            def put_audio_frame(self, _frame, eventpoint):
                emitted.append(eventpoint.get("fragment_sequence"))
                if eventpoint.get("fragment_sequence") == 0:
                    first_pcm.set()

        class FirstCommunicate:
            async def stream(self):
                yield {"type": "audio", "data": payload}
                while not first_hold.is_set():
                    await asyncio.sleep(0.01)

        class SecondCommunicate:
            async def stream(self):
                second_started.set()
                yield {"type": "audio", "data": payload}

        communicates = [FirstCommunicate, SecondCommunicate]

        def communicate(*_args):
            return communicates.pop(0)()

        tts = self._make_tts(Parent())
        tts.put_msg_txt(
            "第一段。",
            {"turn_id": "turn-1", "generation": 1, "fragment_sequence": 0},
        )
        tts.put_msg_txt(
            "第二段。",
            {"turn_id": "turn-1", "generation": 1, "fragment_sequence": 1},
        )
        quit_event = Event()
        worker = Thread(target=tts.process_tts, args=(quit_event,))
        with patch("src.tts.engines.edge.edge_tts.Communicate", side_effect=communicate):
            worker.start()
            try:
                self.assertTrue(first_pcm.wait(timeout=1.5))
                self.assertTrue(second_started.wait(timeout=1.5))
                self.assertNotIn(1, emitted)
                first_hold.set()
                deadline = time.time() + 1.5
                while 1 not in emitted and time.time() < deadline:
                    time.sleep(0.01)
                self.assertIn(1, emitted)
                self.assertLess(emitted.index(0), emitted.index(1))
            finally:
                quit_event.set()
                worker.join(timeout=2)

    def test_all_queued_fragments_begin_synthesis_before_first_finishes(self):
        payload = _mp3_fixture()
        first_pcm = Event()
        first_hold = Event()
        started = [Event(), Event(), Event()]
        emitted = []

        class Parent:
            def put_audio_frame(self, _frame, eventpoint):
                emitted.append(eventpoint.get("fragment_sequence"))
                if eventpoint.get("fragment_sequence") == 0:
                    first_pcm.set()

        class Communicate:
            def __init__(self, index):
                self.index = index

            async def stream(self):
                started[self.index].set()
                yield {"type": "audio", "data": payload}
                if self.index == 0:
                    while not first_hold.is_set():
                        await asyncio.sleep(0.01)

        next_index = 0

        def communicate(*_args):
            nonlocal next_index
            result = Communicate(next_index)
            next_index += 1
            return result

        tts = self._make_tts(Parent())
        for index in range(3):
            tts.put_msg_txt(
                f"第 {index + 1} 段。",
                {"turn_id": "turn-1", "generation": 1, "fragment_sequence": index},
            )
        quit_event = Event()
        worker = Thread(target=tts.process_tts, args=(quit_event,))
        with patch("src.tts.engines.edge.edge_tts.Communicate", side_effect=communicate):
            worker.start()
            try:
                self.assertTrue(first_pcm.wait(timeout=1.5))
                self.assertTrue(started[1].wait(timeout=1.5))
                self.assertTrue(started[2].wait(timeout=1.5))
                self.assertNotIn(1, emitted)
                self.assertNotIn(2, emitted)
                first_hold.set()
                deadline = time.time() + 1.5
                while 2 not in emitted and time.time() < deadline:
                    time.sleep(0.01)
                self.assertLess(emitted.index(0), emitted.index(1))
                self.assertLess(emitted.index(1), emitted.index(2))
            finally:
                quit_event.set()
                worker.join(timeout=2)

    def test_mouth_backpressure_does_not_block_later_tts_network_requests(self):
        """Full LLM text must keep synthesizing while PCM waits for playback."""
        payload = _mp3_fixture()
        blocked = Event()
        release = Event()
        later_started = Event()
        stages = []

        class Parent:
            def mark_stage_end(self, stage):
                stages.append(stage)

            def put_audio_frame(self, _frame, eventpoint):
                if eventpoint.get("fragment_sequence") == 0:
                    blocked.set()
                    release.wait(timeout=2)

        class Communicate:
            def __init__(self, index):
                self.index = index

            async def stream(self):
                if self.index == 1:
                    later_started.set()
                yield {"type": "audio", "data": payload}

        next_index = 0

        def communicate(*_args):
            nonlocal next_index
            result = Communicate(next_index)
            next_index += 1
            return result

        tts = self._make_tts(Parent())
        for index in range(2):
            tts.put_msg_txt(
                "聲音應該連續播放。",
                {"turn_id": "turn-1", "generation": 1, "fragment_sequence": index},
            )
        quit_event = Event()
        worker = Thread(target=tts.process_tts, args=(quit_event,))
        with patch("src.tts.engines.edge.edge_tts.Communicate", side_effect=communicate):
            worker.start()
            try:
                self.assertTrue(blocked.wait(timeout=1))
                self.assertIn("tts_pcm_available", stages)
                self.assertNotIn("tts_first_pcm", stages)
                self.assertTrue(
                    later_started.wait(timeout=0.25),
                    "PCM backpressure blocked the shared TTS network loop",
                )
            finally:
                release.set()
                quit_event.set()
                worker.join(timeout=3)

    def test_flush_talk_drops_prefetched_fragment_audio(self):
        payload = _mp3_fixture()
        first_pcm = Event()
        second_started = Event()
        first_hold = Event()
        emitted = []

        class Parent:
            def put_audio_frame(self, _frame, eventpoint):
                emitted.append(eventpoint.get("fragment_sequence"))
                if eventpoint.get("fragment_sequence") == 0:
                    first_pcm.set()

        class FirstCommunicate:
            async def stream(self):
                yield {"type": "audio", "data": payload}
                while not first_hold.is_set():
                    await asyncio.sleep(0.01)

        class SecondCommunicate:
            async def stream(self):
                second_started.set()
                yield {"type": "audio", "data": payload}
                await asyncio.sleep(0.05)

        communicates = [FirstCommunicate, SecondCommunicate]

        def communicate(*_args):
            return communicates.pop(0)()

        tts = self._make_tts(Parent())
        tts.put_msg_txt(
            "第一段。",
            {"turn_id": "turn-1", "generation": 1, "fragment_sequence": 0},
        )
        tts.put_msg_txt(
            "第二段。",
            {"turn_id": "turn-1", "generation": 1, "fragment_sequence": 1},
        )
        quit_event = Event()
        worker = Thread(target=tts.process_tts, args=(quit_event,))
        with patch("src.tts.engines.edge.edge_tts.Communicate", side_effect=communicate):
            worker.start()
            try:
                self.assertTrue(first_pcm.wait(timeout=1.5))
                self.assertTrue(second_started.wait(timeout=1.5))
                tts.flush_talk()
                first_hold.set()
                worker.join(timeout=0.2)
            finally:
                quit_event.set()
                worker.join(timeout=2)

        self.assertNotIn(1, emitted)

    def test_in_flight_poll_timeout_is_not_a_synthesis_failure(self):
        payload = _mp3_fixture()
        first_pcm = Event()
        first_hold = Event()
        failures = []

        class Parent:
            def put_audio_frame(self, _frame, eventpoint):
                if eventpoint.get("fragment_sequence") == 0:
                    first_pcm.set()

            def notify_fragment_synthesis_failed(self, _eventpoint, reason):
                failures.append(reason)

        class FirstCommunicate:
            async def stream(self):
                yield {"type": "audio", "data": payload}
                while not first_hold.is_set():
                    await asyncio.sleep(0.01)

        tts = self._make_tts(Parent())
        tts.put_msg_txt(
            "第一段。",
            {"turn_id": "turn-1", "generation": 1, "fragment_sequence": 0},
        )
        quit_event = Event()
        worker = Thread(target=tts.process_tts, args=(quit_event,))
        with patch(
            "src.tts.engines.edge.edge_tts.Communicate",
            side_effect=lambda *_args: FirstCommunicate(),
        ):
            worker.start()
            try:
                self.assertTrue(first_pcm.wait(timeout=1.5))
                time.sleep(0.2)
                self.assertEqual(failures, [])
            finally:
                first_hold.set()
                quit_event.set()
                worker.join(timeout=2)

        self.assertEqual(failures, [])

    def test_worker_close_stops_the_background_loop(self):
        class Parent:
            def put_audio_frame(self, _frame, _eventpoint):
                return None

        tts = self._make_tts(Parent())
        tts._ensure_worker()
        loop = tts.worker_loop
        thread = tts._worker.thread
        self.assertTrue(loop.is_running())
        tts.close_worker()
        self.assertFalse(loop.is_running())
        self.assertFalse(thread.is_alive())

    def test_ready_next_fragment_is_enqueued_before_previous_playback_ends(self):
        payload = _mp3_fixture()
        first_complete, second_complete = Event(), Event()
        emitted = []

        class Parent:
            def fragment_playback_ended(self, _eventpoint):
                return False  # PCM is queued, but playback has not caught up.

            def put_audio_frame(self, _frame, eventpoint):
                sequence = eventpoint['fragment_sequence']
                emitted.append(sequence)
                if eventpoint.get('status') == 'end':
                    (first_complete if sequence == 0 else second_complete).set()

        class WorkingCommunicate:
            async def stream(self):
                yield {'type': 'audio', 'data': payload}

        tts = self._make_tts(Parent())
        for sequence in range(2):
            tts.put_msg_txt('固定回答。', {'turn_id': 'turn', 'generation': 1,
                                      'fragment_sequence': sequence})
        quit_event = Event()
        worker = Thread(target=tts.process_tts, args=(quit_event,))
        with patch('src.tts.engines.edge.edge_tts.Communicate',
                   side_effect=lambda *_args: WorkingCommunicate()):
            worker.start()
            try:
                self.assertTrue(first_complete.wait(timeout=1.5))
                self.assertTrue(second_complete.wait(timeout=.8))
                self.assertEqual(emitted, sorted(emitted))
            finally:
                quit_event.set()
                worker.join(timeout=2)
        self.assertFalse(worker.is_alive())

    def test_last_fragment_prefetch_releases_and_completes_promptly(self):
        payload = _mp3_fixture()
        first_pcm = Event()
        first_hold = Event()
        second_end = Event()
        emitted_second = []

        class Parent:
            def put_audio_frame(self, _frame, eventpoint):
                seq = eventpoint.get("fragment_sequence")
                if seq == 0:
                    first_pcm.set()
                elif seq == 1:
                    emitted_second.append(eventpoint)
                    if eventpoint.get("status") == "end":
                        second_end.set()

        class FirstCommunicate:
            async def stream(self):
                yield {"type": "audio", "data": payload}
                while not first_hold.is_set():
                    await asyncio.sleep(0.01)

        class SecondCommunicate:
            async def stream(self):
                # Yield enough audio chunks so it exceeds MAX_PREFETCH_FRAMES (50 frames)
                # and enters wait_for_space() while first fragment is held.
                for _ in range(20):
                    yield {"type": "audio", "data": payload}
                    await asyncio.sleep(0.005)

        communicates = [FirstCommunicate, SecondCommunicate]

        def communicate(*_args):
            return communicates.pop(0)()

        tts = self._make_tts(Parent())
        tts.put_msg_txt(
            "第一段。",
            {"turn_id": "turn-1", "generation": 1, "fragment_sequence": 0},
        )
        tts.put_msg_txt(
            "第二段（最後一片段）。",
            {"turn_id": "turn-1", "generation": 1, "fragment_sequence": 1},
        )
        quit_event = Event()
        worker = Thread(target=tts.process_tts, args=(quit_event,))
        with patch("src.tts.engines.edge.edge_tts.Communicate", side_effect=communicate):
            worker.start()
            try:
                self.assertTrue(first_pcm.wait(timeout=1.5))
                # Allow second fragment to buffer and block in wait_for_space
                time.sleep(0.15)
                # Release first fragment so second fragment is released as the last fragment
                first_hold.set()
                # Second fragment must complete promptly (< 2.0 seconds), NOT hang for 30s
                start = time.perf_counter()
                self.assertTrue(second_end.wait(timeout=2.0), f"Timed out waiting for second fragment end (took {time.perf_counter() - start:.3f}s)")
                self.assertTrue(any(e.get("status") == "end" for e in emitted_second))
            finally:
                quit_event.set()
                worker.join(timeout=2)
