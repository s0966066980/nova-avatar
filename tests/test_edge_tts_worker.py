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

from src.server.app import _await_edge_tts_prewarm, _start_edge_tts_prewarm
from tests.edge_fakes import (
    _handshake_error,
    _mp3_fixture,  # noqa: F401
)


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
            worker = _start_edge_tts_prewarm(self._config("breezyvoice"))
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

        from nova_contracts.tts import PlayableFragment
        from src.tts.retry import RetryBudget
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


class Parent:
    def __init__(self):
        self.frames = []
        self.failures = []

    def put_audio_frame(self, frame, eventpoint):
        self.frames.append(eventpoint)

    def on_fragment_synthesis_failed(self, textevent, reason):
        self.failures.append(reason)


class FakeEdge:
    """Hands out scripted connections in order and records how each ended."""

    def __init__(self, *behaviours):
        self.behaviours = list(behaviours)
        self.opened = 0
        self.closed = []
        self.payload = _mp3_fixture()

    def __call__(self, *_args):
        behaviour = self.behaviours[self.opened]
        index = self.opened
        self.opened += 1
        edge = self

        class Connection:
            async def stream(self):
                try:
                    if behaviour == "429":
                        raise _handshake_error(429)
                    yield {"type": "audio", "data": edge.payload}
                finally:
                    edge.closed.append(index)

        return Connection()


class EdgeResilienceTests(unittest.TestCase):
    def make_tts(self, parent):
        from src.tts.engines.edge import EdgeTTS

        config = SimpleNamespace(
            audio=SimpleNamespace(fps=50),
            tts=SimpleNamespace(
                ref_file="zh-TW-YunJheNeural",
                edge_persistent_worker=True,
                edge_prefetch=True,
            ),
        )
        tts = EdgeTTS(config, parent)
        self.addCleanup(tts.close_worker)
        return tts

    def speak(self, edge, textevent=None, *, uniform=None):
        parent = Parent()
        tts = self.make_tts(parent)
        patches = [
            patch("src.tts.engines.edge.edge_tts.Communicate", side_effect=edge),
            patch("src.tts.engines.edge.EDGE_RATE_LIMIT_BACKOFF_SECONDS", 0.001),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        tts.txt_to_audio(("測試首音。", dict(textevent or {})))
        return parent

    def test_a_429_is_retried_after_the_shared_cooldown(self):
        edge = FakeEdge("429", "ok")
        parent = self.speak(edge)
        self.assertTrue(parent.frames)
        self.assertEqual(edge.opened, 2)
        self.assertEqual(edge.closed, [0, 1])

    def test_repeated_429_cannot_expand_the_retry_budget(self):
        edge = FakeEdge("429", "429", "ok")
        parent = self.speak(edge)
        self.assertFalse(parent.frames)
        self.assertEqual(edge.opened, 2)
        self.assertEqual(edge.closed, [0, 1])


class EdgeTTSSilenceTests(unittest.TestCase):
    def test_trims_synthesizer_padding_but_keeps_short_natural_pause(self):
        from src.tts.engines.edge import trim_edge_silence

        sample_rate = 16000
        stream = np.concatenate(
            [
                np.zeros(int(sample_rate * 0.10), dtype=np.float32),
                np.full(int(sample_rate * 0.50), 0.1, dtype=np.float32),
                np.zeros(int(sample_rate * 0.72), dtype=np.float32),
            ]
        )

        trimmed = trim_edge_silence(stream, sample_rate)

        self.assertEqual(trimmed.shape[0], int(sample_rate * (0.04 + 0.50 + 0.12)))
        self.assertTrue(np.allclose(trimmed[: int(sample_rate * 0.04)], 0.0))
        self.assertTrue(np.allclose(trimmed[-int(sample_rate * 0.12) :], 0.0))

    def test_does_not_drop_an_entire_quiet_clip(self):
        from src.tts.engines.edge import trim_edge_silence

        stream = np.zeros(1600, dtype=np.float32)
        self.assertIs(trim_edge_silence(stream, 16000), stream)

    def test_streaming_trim_matches_batch_trim_across_partial_frames(self):
        from src.tts.engines.edge import (
            _StreamingSilenceTrimmer,
            trim_edge_silence,
        )

        sample_rate = 16000
        stream = np.concatenate(
            [
                np.zeros(1731, dtype=np.float32),
                np.full(8123, 0.1, dtype=np.float32),
                np.zeros(11957, dtype=np.float32),
            ]
        )
        trimmer = _StreamingSilenceTrimmer(sample_rate)
        output = []
        for offset in range(0, stream.size, 137):
            chunk = trimmer.feed(stream[offset : offset + 137])
            if chunk.size:
                output.append(chunk)
        output.append(trimmer.finish())

        self.assertTrue(
            np.array_equal(np.concatenate(output), trim_edge_silence(stream, sample_rate))
        )

    @staticmethod
    def _trim_chunked(stream, sample_rate, sizes):
        from src.tts.engines.edge import _StreamingSilenceTrimmer

        trimmer = _StreamingSilenceTrimmer(sample_rate)
        output = []
        offset = 0
        index = 0
        while offset < stream.size:
            size = sizes[index % len(sizes)]
            chunk = trimmer.feed(stream[offset : offset + size])
            if chunk.size:
                output.append(chunk)
            offset += size
            index += 1
        leftover = trimmer.finish()
        if leftover.size:
            output.append(leftover)
        if not output:
            return np.empty(0, dtype=np.float32), trimmer
        return np.concatenate(output), trimmer

    def test_preserves_low_energy_onset_before_confirmed_speech(self):
        sample_rate = 16000
        quiet_onset = np.full(int(sample_rate * 0.08), 5e-5, dtype=np.float32)
        voiced = np.full(int(sample_rate * 0.02), 0.1, dtype=np.float32)
        source = np.concatenate((quiet_onset, voiced))

        result, _ = self._trim_chunked(source, sample_rate, (173, 1, 160, 320, 137))

        self.assertEqual(result.size, source.size)
        self.assertTrue(np.allclose(result[: quiet_onset.size], quiet_onset))
        self.assertTrue(np.allclose(result[quiet_onset.size :], voiced))

    def test_each_fragment_preserves_its_own_low_energy_onset(self):
        sample_rate = 16000
        quiet_onset = np.full(int(sample_rate * 0.08), 5e-5, dtype=np.float32)
        voiced = np.full(int(sample_rate * 0.02), 0.1, dtype=np.float32)
        source = np.concatenate((quiet_onset, voiced))

        for _ in range(2):
            result, _ = self._trim_chunked(source, sample_rate, (137, 160, 1, 320))
            self.assertEqual(result.size, source.size)
            self.assertTrue(np.allclose(result[: quiet_onset.size], quiet_onset))

    def test_preserves_ramped_low_energy_onset(self):
        sample_rate = 16000
        ramp = np.linspace(2e-5, 8e-5, int(sample_rate * 0.08), dtype=np.float32)
        voiced = np.full(int(sample_rate * 0.02), 0.1, dtype=np.float32)
        source = np.concatenate((ramp, voiced))

        result, _ = self._trim_chunked(source, sample_rate, (137, 160, 320))

        self.assertEqual(result.size, source.size)
        self.assertTrue(np.allclose(result[: ramp.size], ramp, atol=1e-8))

    def test_tiny_codec_residual_does_not_keep_long_padding(self):
        sample_rate = 16000
        residual = np.full(int(sample_rate * 0.10), 1e-6, dtype=np.float32)
        voiced = np.full(int(sample_rate * 0.20), 0.1, dtype=np.float32)
        source = np.concatenate((residual, voiced))

        result, _ = self._trim_chunked(source, sample_rate, (160, 320))

        self.assertEqual(result.size, int(sample_rate * (0.04 + 0.20)))
        self.assertTrue(np.allclose(result[: int(sample_rate * 0.04)], 1e-6))
        self.assertTrue(np.allclose(result[int(sample_rate * 0.04) :], voiced))

    def test_chunk_boundaries_do_not_change_onset_preservation(self):
        from src.tts.engines.edge import trim_edge_silence

        sample_rate = 16000
        quiet_onset = np.full(int(sample_rate * 0.08), 5e-5, dtype=np.float32)
        voiced = np.full(int(sample_rate * 0.12), 0.1, dtype=np.float32)
        source = np.concatenate((quiet_onset, voiced))
        expected = trim_edge_silence(source, sample_rate)
        rng = np.random.default_rng(0)
        size_sets = (
            (1,),
            (137,),
            (160,),
            (320,),
            tuple(int(size) for size in rng.integers(1, 401, size=12)),
        )
        for sizes in size_sets:
            with self.subTest(sizes=sizes):
                result, _ = self._trim_chunked(source, sample_rate, sizes)
                self.assertTrue(np.array_equal(result, expected))


class EdgeTTSStreamingTests(unittest.TestCase):
    @staticmethod
    def _mp3_fixture() -> bytes:
        import av

        sample_rate = 24000
        tone_samples = int(sample_rate * 0.30)
        tone = (
            np.sin(2 * np.pi * 440 * np.arange(tone_samples) / sample_rate)
            * 8000
        ).astype(np.int16)
        samples = np.concatenate(
            [
                np.zeros(int(sample_rate * 0.05), dtype=np.int16),
                tone,
                np.zeros(int(sample_rate * 0.15), dtype=np.int16),
            ]
        )
        output = BytesIO()
        with av.open(output, mode="w", format="mp3") as container:
            stream = container.add_stream("libmp3lame", rate=sample_rate)
            stream.layout = "mono"
            frame = av.AudioFrame.from_ndarray(
                samples.reshape(1, -1), format="s16", layout="mono"
            )
            frame.sample_rate = sample_rate
            for packet in stream.encode(frame):
                container.mux(packet)
            for packet in stream.encode(None):
                container.mux(packet)
        payload = output.getvalue()
        first_audio_frame = payload.find(b"\xff\xf3")
        return payload[first_audio_frame:] if first_audio_frame >= 0 else payload

    @staticmethod
    def _make_tts(parent):
        from src.tts.engines.edge import EdgeTTS

        config = SimpleNamespace(
            audio=SimpleNamespace(fps=50),
            tts=SimpleNamespace(ref_file="zh-TW-YunJheNeural"),
        )
        return EdgeTTS(config, parent)

    def test_pcm_is_emitted_before_remote_stream_finishes(self):
        remote_release = Event()
        first_pcm = Event()

        class Parent:
            def put_audio_frame(self, _frame, _eventpoint):
                first_pcm.set()

        payload = self._mp3_fixture()

        class SlowEndingCommunicate:
            def __init__(self, *_args):
                pass

            async def stream(self):
                yield {"type": "audio", "data": payload}
                while not remote_release.is_set():
                    await asyncio.sleep(0.01)

        tts = self._make_tts(Parent())
        worker = Thread(target=tts.txt_to_audio, args=(("測試即時播放。", {}),))
        with patch("src.tts.engines.edge.edge_tts.Communicate", SlowEndingCommunicate):
            worker.start()
            try:
                self.assertTrue(first_pcm.wait(timeout=0.20))
                self.assertTrue(worker.is_alive())
            finally:
                remote_release.set()
                worker.join(timeout=1)

    def test_timeout_before_first_audio_retries_without_stale_data(self):
        calls = []

        class Parent:
            def __init__(self):
                self.frames = []

            def put_audio_frame(self, frame, eventpoint):
                self.frames.append((frame, eventpoint))

        payload = self._mp3_fixture()

        class TimeoutCommunicate:
            async def stream(self):
                if False:
                    yield None
                raise asyncio.TimeoutError

        class WorkingCommunicate:
            async def stream(self):
                yield {"type": "audio", "data": payload}

        def communicate(*_args):
            calls.append(len(calls) + 1)
            return TimeoutCommunicate() if len(calls) == 1 else WorkingCommunicate()

        parent = Parent()
        tts = self._make_tts(parent)
        with patch("src.tts.engines.edge.edge_tts.Communicate", side_effect=communicate):
            tts.txt_to_audio(("測試逾時重試。", {}))

        self.assertEqual(calls, [1, 2])
        self.assertTrue(parent.frames)
        start_events = [
            event for _, event in parent.frames if event.get("status") == "start"
        ]
        self.assertEqual(len(start_events), 1)

    def test_terminal_timeout_before_audio_reports_fragment_failure(self):
        failures = []

        class Parent:
            def put_audio_frame(self, _frame, _eventpoint):
                raise AssertionError("failed synthesis must not emit audio")

            def notify_fragment_synthesis_failed(self, eventpoint, reason):
                failures.append((dict(eventpoint), reason))

        class TimeoutCommunicate:
            async def stream(self):
                if False:
                    yield None
                raise asyncio.TimeoutError

        metadata = {
            "turn_id": "turn-1",
            "generation": 3,
            "fragment_sequence": 4,
        }
        tts = self._make_tts(Parent())
        with patch(
            "src.tts.engines.edge.edge_tts.Communicate",
            side_effect=lambda *_args: TimeoutCommunicate(),
        ):
            tts.txt_to_audio(("測試最終失敗。", metadata))

        self.assertEqual(
            failures,
            [(metadata, "tts_exhausted_before_audio")],
        )

    def test_timeout_after_partial_audio_does_not_sample_splice(self):
        calls = []

        class Parent:
            def __init__(self):
                self.frames = []

            def put_audio_frame(self, frame, eventpoint):
                self.frames.append((frame.copy(), dict(eventpoint)))

        payload = self._mp3_fixture()

        class PartialTimeoutCommunicate:
            async def stream(self):
                yield {"type": "audio", "data": payload[: len(payload) * 3 // 4]}
                raise asyncio.TimeoutError

        class ShiftedCommunicate:
            async def stream(self):
                yield {"type": "audio", "data": payload}

        def communicate(*_args):
            calls.append(len(calls) + 1)
            return (
                PartialTimeoutCommunicate()
                if len(calls) == 1
                else ShiftedCommunicate()
            )

        parent = Parent()
        tts = self._make_tts(parent)
        with patch("src.tts.engines.edge.edge_tts.Communicate", side_effect=communicate):
            tts.txt_to_audio(("測試中斷不接續。", {}))

        self.assertEqual(calls, [1])
        self.assertTrue(parent.frames)
        self.assertGreater(tts.retry_after_pcm_count, 0)
        self.assertEqual(tts.retry_after_playback_commit_count, 0)

    def test_timeout_after_playback_commit_does_not_retry(self):
        from nova_contracts.tts import PlayableFragment
        from src.server.reply_streaming.turn import TurnContext

        calls = []

        class Parent:
            def __init__(self):
                self.frames = []

            def put_audio_frame(self, frame, eventpoint):
                self.frames.append((frame.copy(), dict(eventpoint)))

        payload = self._mp3_fixture()

        class PartialTimeoutCommunicate:
            async def stream(self):
                yield {"type": "audio", "data": payload[: len(payload) * 3 // 4]}
                raise asyncio.TimeoutError

        def communicate(*_args):
            calls.append(len(calls) + 1)
            return PartialTimeoutCommunicate()

        turn = TurnContext(turn_id="turn-1", generation=1)
        fragment = PlayableFragment(
            envelope=turn.envelope(stage="tts_fragment", sequence=0),
            text="測試提交後不重試。",
            estimated_seconds=0.5,
        )
        parent = Parent()
        tts = self._make_tts(parent)
        with patch("src.tts.engines.edge.edge_tts.Communicate", side_effect=communicate):
            tts.synthesize_fragment(
                fragment,
                chunk_guard=lambda _sequence: True,
                fragment_committed=lambda: True,
            )

        self.assertEqual(calls, [1])
        self.assertTrue(parent.frames)
        self.assertEqual(tts.retry_after_playback_commit_count, 1)

    def test_turn_aware_frames_are_fenced_and_keep_20ms_media_sequences(self):
        from nova_contracts.tts import PlayableFragment
        from src.server.reply_streaming.turn import TurnContext

        class Parent:
            def __init__(self):
                self.frames = []

            def put_audio_frame(self, frame, eventpoint):
                self.frames.append((frame.copy(), dict(eventpoint)))

        payload = self._mp3_fixture()

        class WorkingCommunicate:
            async def stream(self):
                yield {"type": "audio", "data": payload}

        turn = TurnContext(turn_id="turn-1", generation=7)
        fragment = PlayableFragment(
            envelope=turn.envelope(stage="tts_fragment", sequence=3),
            text="測試輪次音訊。",
            estimated_seconds=0.5,
        )
        parent = Parent()
        tts = self._make_tts(parent)

        with patch(
            "src.tts.engines.edge.edge_tts.Communicate",
            side_effect=lambda *_args: WorkingCommunicate(),
        ):
            tts.synthesize_fragment(
                fragment,
                chunk_guard=lambda media_sequence: media_sequence < 2,
            )

        self.assertEqual(len(parent.frames), 2)
        self.assertTrue(all(frame.shape == (320,) for frame, _ in parent.frames))
        self.assertEqual(
            [event["media_sequence"] for _, event in parent.frames],
            [0, 1],
        )
        self.assertTrue(
            all(
                event["turn_id"] == "turn-1"
                and event["generation"] == 7
                and event["fragment_sequence"] == 3
                for _, event in parent.frames
            )
        )

    def test_fragment_retry_uses_the_shared_one_second_budget(self):
        from nova_contracts.tts import PlayableFragment
        from src.tts.retry import RetryBudget
        from src.server.reply_streaming.turn import TurnContext
        from src.tts.engines.edge import EDGE_INITIAL_STREAM_TIMEOUT_SECONDS

        class Parent:
            def put_audio_frame(self, _frame, _eventpoint):
                raise AssertionError("timed out attempts must not emit audio")

        class HangingCommunicate:
            async def stream(self):
                await asyncio.Event().wait()
                if False:
                    yield None

        timeouts = []

        async def immediate_timeout(awaitable, *, timeout):
            timeouts.append(timeout)
            awaitable.close()
            raise asyncio.TimeoutError

        turn = TurnContext(turn_id="turn-1", generation=1)
        fragment = PlayableFragment(
            envelope=turn.envelope(stage="tts_fragment", sequence=0),
            text="測試重試預算。",
            estimated_seconds=0.5,
        )
        tts = self._make_tts(Parent())

        with (
            patch(
                "src.tts.engines.edge.edge_tts.Communicate",
                side_effect=lambda *_args: HangingCommunicate(),
            ),
            patch("src.tts.engines.edge.asyncio.wait_for", new=immediate_timeout),
        ):
            tts.synthesize_fragment(
                fragment,
                chunk_guard=lambda _sequence: True,
                retry_budget=RetryBudget(max_retries=1, extra_wait_seconds=1.0),
            )

        self.assertEqual(
            timeouts,
            [EDGE_INITIAL_STREAM_TIMEOUT_SECONDS, 1.0],
        )

    def test_default_retry_allows_a_slow_edge_first_byte(self):
        from src.tts.engines.edge import (
            EDGE_INITIAL_STREAM_TIMEOUT_SECONDS,
            EDGE_RETRY_STREAM_TIMEOUT_SECONDS,
        )

        class Parent:
            def put_audio_frame(self, _frame, _eventpoint):
                raise AssertionError("timed out attempts must not emit audio")

        class HangingCommunicate:
            async def stream(self):
                await asyncio.Event().wait()
                if False:
                    yield None

        timeouts = []

        async def immediate_timeout(awaitable, *, timeout):
            timeouts.append(timeout)
            awaitable.close()
            raise asyncio.TimeoutError

        tts = self._make_tts(Parent())
        with (
            patch(
                "src.tts.engines.edge.edge_tts.Communicate",
                side_effect=lambda *_args: HangingCommunicate(),
            ),
            patch("src.tts.engines.edge.asyncio.wait_for", new=immediate_timeout),
        ):
            tts.txt_to_audio(("測試慢速首包。", {}))

        self.assertEqual(
            timeouts,
            [
                EDGE_INITIAL_STREAM_TIMEOUT_SECONDS,
                EDGE_RETRY_STREAM_TIMEOUT_SECONDS,
            ],
        )
        self.assertGreaterEqual(EDGE_RETRY_STREAM_TIMEOUT_SECONDS, 15.0)

    def test_first_attempt_switches_to_continuation_timeout_after_audio(self):
        from src.tts.engines.edge import (
            EDGE_CONTINUATION_STREAM_TIMEOUT_SECONDS,
            EDGE_INITIAL_STREAM_TIMEOUT_SECONDS,
        )

        class Parent:
            def __init__(self):
                self.frames = []

            def put_audio_frame(self, frame, eventpoint):
                self.frames.append((frame.copy(), dict(eventpoint)))

        payload = self._mp3_fixture()

        class WorkingCommunicate:
            async def stream(self):
                yield {"type": "audio", "data": payload}

        timeouts = []
        real_wait_for = asyncio.wait_for

        async def recording_wait_for(awaitable, *, timeout):
            timeouts.append(timeout)
            return await real_wait_for(awaitable, timeout=timeout)

        parent = Parent()
        tts = self._make_tts(parent)
        with (
            patch(
                "src.tts.engines.edge.edge_tts.Communicate",
                side_effect=lambda *_args: WorkingCommunicate(),
            ),
            patch(
                "src.tts.engines.edge.asyncio.wait_for",
                new=recording_wait_for,
            ),
        ):
            tts.txt_to_audio(("測試串流續包逾時。", {}))

        self.assertTrue(parent.frames)
        self.assertEqual(timeouts[0], EDGE_INITIAL_STREAM_TIMEOUT_SECONDS)
        self.assertEqual(
            timeouts[1:],
            [EDGE_CONTINUATION_STREAM_TIMEOUT_SECONDS],
        )

    def test_edge_prewarm_stops_after_first_audio_packet(self):
        from src.tts.engines.edge import prewarm_edge_tts

        calls = []

        class WarmupCommunicate:
            async def stream(self):
                calls.append("metadata")
                yield {"type": "WordBoundary", "text": "預熱"}
                calls.append("audio")
                yield {"type": "audio", "data": b"warm"}
                calls.append("too-far")
                yield {"type": "audio", "data": b"unused"}

        with patch(
            "src.tts.engines.edge.edge_tts.Communicate",
            side_effect=lambda *_args: WarmupCommunicate(),
        ):
            ready = prewarm_edge_tts("zh-TW-YunJheNeural", timeout_seconds=0.5)

        self.assertTrue(ready)
        self.assertEqual(calls, ["metadata", "audio"])
