import asyncio
import queue
import time
import unittest
from io import BytesIO
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import numpy as np

from src.llm.base import TextStreamProcessor
from src.tts.base import BaseTTS


class TTSSpeechTextTests(unittest.TestCase):
    def test_tts_queue_removes_markdown_markers_and_emoji_before_synthesis(self):
        config = SimpleNamespace(audio=SimpleNamespace(fps=50))
        tts = BaseTTS(config, SimpleNamespace())

        tts.put_msg_txt("**這很重要**，請確認。😊")

        text, metadata = tts.msgqueue.get_nowait()
        self.assertEqual(text, "這很重要，請確認。")
        self.assertEqual(metadata, {})


class WebRTCPacingTests(unittest.IsolatedAsyncioTestCase):
    async def test_player_reports_media_debt_and_av_offset_without_frames(self):
        from src.utils.webrtc import HumanPlayer

        observations = []
        player = HumanPlayer(
            None,
            on_media_timing=lambda **values: observations.append(values),
        )
        await player.audio.enqueue(object())
        await player.video.enqueue(object())

        eventpoint = {"turn_id": "turn-1", "generation": 0, "media_sequence": 0}
        player.notify_media_timing("audio", 0.10, eventpoint)
        player.notify_media_timing("video", 0.14, eventpoint)

        self.assertEqual(
            observations[-1],
            {
                "media_debt_seconds": 0.02,
                "av_offset_seconds": 0.04,
            },
        )
        player.audio.stop()
        player.video.stop()

    async def test_player_ignores_unpaired_media_for_av_metric(self):
        from src.utils.webrtc import HumanPlayer

        observations = []
        player = HumanPlayer(
            None,
            on_media_timing=lambda **values: observations.append(values),
        )

        player.notify_media_timing(
            "audio",
            0.10,
            {"turn_id": "turn-1", "generation": 0, "media_sequence": 0},
        )
        player.notify_media_timing(
            "video",
            0.26,
            {"turn_id": "turn-1", "generation": 0, "media_sequence": 3},
        )

        self.assertIsNone(observations[-1]["av_offset_seconds"])
        player.audio.stop()
        player.video.stop()

    async def test_speech_start_discards_only_paired_idle_runway(self):
        from src.utils.webrtc import HumanPlayer, VIDEO_PTIME

        player = HumanPlayer(None)
        audio = player.audio
        video = player.video
        for _ in range(audio.max_buffer_frames):
            await audio.enqueue(object())
        for _ in range(video.max_buffer_frames):
            await video.enqueue(object())

        await player.prepare_speech_start()

        # Keep at most one paired 40 ms idle runway.  A longer runway is
        # audible as avoidable silence before the first spoken PCM packet.
        self.assertLessEqual(audio.buffered_duration, 0.06)
        self.assertLessEqual(video.buffered_duration, 0.06)
        self.assertLessEqual(
            abs(audio.buffered_duration - video.buffered_duration),
            VIDEO_PTIME,
        )
        audio.stop()
        video.stop()

    async def test_audio_and_video_apply_equal_low_latency_backpressure(self):
        from src.utils.webrtc import HumanPlayer

        player = HumanPlayer(None)
        audio = player.audio
        video = player.video

        self.assertLessEqual(audio.max_buffer_duration, 0.25)
        self.assertAlmostEqual(
            audio.max_buffer_duration,
            video.max_buffer_duration,
            places=3,
        )

        for _ in range(audio.max_buffer_frames):
            await audio.enqueue(object())
        blocked_put = asyncio.create_task(audio.enqueue(object()))
        await asyncio.sleep(0)

        self.assertFalse(blocked_put.done())
        self.assertLessEqual(audio.buffered_duration, 0.25)

        blocked_put.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await blocked_put
        audio.stop()
        video.stop()

    async def test_audio_and_video_share_one_stall_rebase(self):
        from src.utils.webrtc import HumanPlayer

        now = [100.0]
        sleeper = AsyncMock()
        player = HumanPlayer(None)
        audio = player.audio
        video = player.video

        with (
            patch("src.utils.webrtc.time.time", side_effect=lambda: now[0]),
            patch("src.utils.webrtc.time.monotonic", side_effect=lambda: now[0]),
            patch("src.utils.webrtc.asyncio.sleep", new=sleeper),
            patch("src.utils.webrtc.mylogger") as pacing_logger,
        ):
            await audio.next_timestamp()
            await video.next_timestamp()
            now[0] += 1.0
            await audio.next_timestamp()
            now[0] += 0.08
            await video.next_timestamp()

        self.assertAlmostEqual(audio._start, video._start, places=6)
        pacing_logger.warning.assert_called_once()
        audio.stop()
        video.stop()

    async def test_audio_rebases_and_video_skips_after_stall_without_bursting(self):
        from src.utils.webrtc import (
            AUDIO_PTIME,
            SAMPLE_RATE,
            VIDEO_CLOCK_RATE,
            VIDEO_PTIME,
            PlayerStreamTrack,
        )

        cases = (
            ("audio", AUDIO_PTIME, SAMPLE_RATE),
            ("video", VIDEO_PTIME, VIDEO_CLOCK_RATE),
        )
        for kind, packet_time, clock_rate in cases:
            with self.subTest(kind=kind):
                now = [100.0]
                sleeper = AsyncMock()
                track = PlayerStreamTrack(None, kind=kind)

                with (
                    patch("src.utils.webrtc.time.time", side_effect=lambda: now[0]),
                    patch("src.utils.webrtc.time.monotonic", side_effect=lambda: now[0]),
                    patch("src.utils.webrtc.asyncio.sleep", new=sleeper),
                    patch("src.utils.webrtc.mylogger") as pacing_logger,
                ):
                    first_pts, _ = await track.next_timestamp()
                    now[0] += 1.0
                    second_pts, _ = await track.next_timestamp()
                    third_pts, _ = await track.next_timestamp()

                sleeper.assert_awaited_once()
                pacing_logger.warning.assert_called_once()
                self.assertAlmostEqual(
                    sleeper.await_args.args[0], packet_time, places=6
                )
                packet_ticks = int(packet_time * clock_rate)
                expected = (
                    [0, packet_ticks, packet_ticks * 2]
                    if kind == "audio"
                    else [0, clock_rate, clock_rate + packet_ticks]
                )
                self.assertEqual([first_pts, second_pts, third_pts], expected)
                track.stop()

    async def test_video_does_not_release_catch_up_frames_after_short_stall(self):
        from src.utils.webrtc import VIDEO_PTIME, PlayerStreamTrack

        now = [100.0]
        deliveries = []

        async def fake_sleep(delay):
            now[0] += delay

        track = PlayerStreamTrack(None, kind="video")
        with (
            patch("src.utils.webrtc.time.monotonic", side_effect=lambda: now[0]),
            patch("src.utils.webrtc.asyncio.sleep", new=fake_sleep),
            patch("src.utils.webrtc.mylogger"),
        ):
            await track.next_timestamp()
            deliveries.append(now[0])
            now[0] += 0.080
            for _ in range(4):
                await track.next_timestamp()
                deliveries.append(now[0])

        intervals = [
            deliveries[index] - deliveries[index - 1]
            for index in range(1, len(deliveries))
        ]
        self.assertGreaterEqual(intervals[0], 0.079)
        for interval in intervals[1:]:
            self.assertGreaterEqual(interval, VIDEO_PTIME - 0.001)
        track.stop()

    async def test_audio_does_not_catch_up_after_sub_threshold_stall(self):
        from src.utils.webrtc import AUDIO_PTIME, SAMPLE_RATE, PlayerStreamTrack

        now = [100.0]
        deliveries = []

        async def fake_sleep(delay):
            now[0] += delay

        track = PlayerStreamTrack(None, kind="audio")
        with (
            patch("src.utils.webrtc.time.monotonic", side_effect=lambda: now[0]),
            patch("src.utils.webrtc.asyncio.sleep", new=fake_sleep),
            patch("src.utils.webrtc.mylogger"),
        ):
            pts_list = []
            first_pts, _ = await track.next_timestamp()
            pts_list.append(first_pts)
            deliveries.append(now[0])
            now[0] += 0.090
            for _ in range(5):
                pts, _ = await track.next_timestamp()
                pts_list.append(pts)
                deliveries.append(now[0])

        packet_ticks = int(AUDIO_PTIME * SAMPLE_RATE)
        self.assertEqual(pts_list, [index * packet_ticks for index in range(6)])
        intervals = [
            round(deliveries[index] - deliveries[index - 1], 6)
            for index in range(1, len(deliveries))
        ]
        self.assertGreaterEqual(intervals[0], 0.089)
        for interval in intervals[1:]:
            self.assertGreater(interval, 0.015)
            self.assertLess(interval, 0.025)
        self.assertFalse(
            any(
                left < 0.005 and right < 0.005
                for left, right in zip(intervals, intervals[1:])
            )
        )
        self.assertEqual(track.catch_up_burst_count, 0)
        track.stop()

    async def test_audio_recovers_20ms_pacing_after_short_stalls(self):
        from src.utils.webrtc import AUDIO_PTIME, SAMPLE_RATE, PlayerStreamTrack

        for stall in (0.030, 0.050, 0.090, 0.100, 1.0):
            with self.subTest(stall=stall):
                now = [100.0]

                async def fake_sleep(delay):
                    now[0] += delay

                track = PlayerStreamTrack(None, kind="audio")
                with (
                    patch("src.utils.webrtc.time.monotonic", side_effect=lambda: now[0]),
                    patch("src.utils.webrtc.asyncio.sleep", new=fake_sleep),
                    patch("src.utils.webrtc.mylogger"),
                ):
                    pts_list = []
                    deliveries = []
                    first_pts, _ = await track.next_timestamp()
                    pts_list.append(first_pts)
                    deliveries.append(now[0])
                    now[0] += stall
                    for _ in range(4):
                        pts, _ = await track.next_timestamp()
                        pts_list.append(pts)
                        deliveries.append(now[0])

                packet_ticks = int(AUDIO_PTIME * SAMPLE_RATE)
                self.assertEqual(
                    pts_list,
                    [index * packet_ticks for index in range(5)],
                )
                intervals = [
                    round(deliveries[index] - deliveries[index - 1], 6)
                    for index in range(1, len(deliveries))
                ]
                self.assertGreaterEqual(intervals[0], stall - 0.001)
                for interval in intervals[1:]:
                    self.assertGreater(interval, 0.015)
                    self.assertLess(interval, 0.025)
                self.assertEqual(track.catch_up_burst_count, 0)
                track.stop()

    async def test_audio_pacing_callback_is_content_free(self):
        from src.utils.webrtc import HumanPlayer

        observations = []
        now = [100.0]

        async def fake_sleep(delay):
            now[0] += delay

        player = HumanPlayer(
            None,
            on_audio_pacing=lambda **values: observations.append(values),
        )
        with (
            patch("src.utils.webrtc.time.monotonic", side_effect=lambda: now[0]),
            patch("src.utils.webrtc.asyncio.sleep", new=fake_sleep),
            patch("src.utils.webrtc.mylogger"),
        ):
            await player.audio.next_timestamp()
            now[0] += 0.090
            await player.audio.next_timestamp()
            await player.audio.next_timestamp()

        self.assertTrue(observations)
        self.assertGreaterEqual(observations[-1]["rebase_count"], 1)
        self.assertEqual(observations[-1]["catch_up_burst_count"], 0)
        self.assertTrue(
            {"text", "transcript", "pcm", "samples"}.isdisjoint(observations[-1])
        )
        player.audio.stop()
        player.video.stop()


class TextStreamTimingTests(unittest.TestCase):
    def test_comma_clause_waits_for_sentence_end(self):
        emitted = []
        processor = TextStreamProcessor()

        processor.process_chunk("我是 Linly 數字人助手，", emitted.append)
        self.assertEqual(emitted, [])

        processor.process_chunk("很高興為你服務，也可以協助處理各種問題。", emitted.append)
        self.assertEqual(
            emitted,
            ["我是 Linly 數字人助手，很高興為你服務，也可以協助處理各種問題。"],
        )


class MuseTalkAudioWindowTests(unittest.TestCase):
    def test_feature_window_is_centered_on_the_video_frame(self):
        from src.avatars.musetalk.whisper.audio2feature import Audio2Feature

        processor = Audio2Feature.__new__(Audio2Feature)
        features = np.zeros((64, 5, 384), dtype=np.float32)

        _, selected = processor.get_sliced_feature(
            features,
            vid_idx=5,
            audio_feat_length=[2, 2],
            fps=25,
        )

        self.assertEqual(selected, list(range(6, 16)))


class MuseTalkBufferPolicyTests(unittest.TestCase):
    def test_empty_batch_uses_one_blocking_poll(self):
        from src.avatars.audio_stream_handler import BaseAudioStreamHandler

        config = SimpleNamespace(
            audio=SimpleNamespace(fps=50, l=2, r=2),
            model=SimpleNamespace(batch_size=8),
        )
        handler = BaseAudioStreamHandler(config, parent=None)
        started = time.perf_counter()
        frames = handler.get_audio_frames(16)
        elapsed = time.perf_counter() - started

        self.assertEqual(len(frames), 16)
        self.assertLess(elapsed, 0.08)

    def test_waits_for_pending_tts_while_playback_has_headroom(self):
        from src.avatars.musetalk.avatar import should_wait_for_tts_audio

        self.assertTrue(
            should_wait_for_tts_audio(
                tts_pending=True,
                queued_audio_frames=8,
                required_audio_frames=32,
                queued_video_frames=5,
            )
        )

    def test_partial_tts_batch_waits_instead_of_inserting_mid_speech_silence(self):
        from src.avatars.musetalk.avatar import should_wait_for_tts_audio

        # Once real speech has entered the queue, consuming a short batch makes
        # run_step() fill the remainder with timeout-generated silence.  Keep
        # the partial batch intact even when the video runway is temporarily low.
        self.assertTrue(
            should_wait_for_tts_audio(True, 8, 32, queued_video_frames=4)
        )

    def test_pending_tts_wait_is_bounded_to_keep_idle_video_advancing(self):
        from src.avatars.musetalk.avatar import (
            MAX_TTS_AUDIO_WAIT_SECONDS,
            should_wait_for_tts_audio,
        )

        self.assertTrue(
            should_wait_for_tts_audio(
                True,
                8,
                32,
                queued_video_frames=5,
                pending_wait_seconds=MAX_TTS_AUDIO_WAIT_SECONDS - 0.001,
            )
        )
        self.assertFalse(
            should_wait_for_tts_audio(
                True,
                8,
                32,
                queued_video_frames=5,
                pending_wait_seconds=MAX_TTS_AUDIO_WAIT_SECONDS,
            )
        )

    def test_does_not_starve_idle_playback_or_delay_ready_audio(self):
        from src.avatars.musetalk.avatar import should_wait_for_tts_audio

        self.assertFalse(
            should_wait_for_tts_audio(True, 0, 32, queued_video_frames=4)
        )
        self.assertFalse(
            should_wait_for_tts_audio(True, 32, 32, queued_video_frames=5)
        )
        self.assertFalse(
            should_wait_for_tts_audio(False, 0, 32, queued_video_frames=5)
        )

    def test_tts_reports_work_while_synthesis_is_active(self):
        started = Event()
        release = Event()
        quit_event = Event()

        class BlockingTTS(BaseTTS):
            def txt_to_audio(self, msg):
                started.set()
                release.wait(timeout=1)

        config = SimpleNamespace(audio=SimpleNamespace(fps=50))
        tts = BlockingTTS(config, parent=None)
        tts.put_msg_txt("測試語音")
        worker = Thread(target=tts.process_tts, args=(quit_event,), daemon=True)
        worker.start()

        self.assertTrue(started.wait(timeout=1))
        self.assertTrue(tts.has_pending_work())

        quit_event.set()
        release.set()
        worker.join(timeout=1)
        self.assertFalse(tts.has_pending_work())


class MuseTalkShutdownTests(unittest.TestCase):
    def test_full_result_queue_releases_inference_when_stopping(self):
        from src.avatars.musetalk.avatar import put_result_frame

        result_queue = queue.Queue(maxsize=1)
        result_queue.put(object())
        quit_event = Event()
        outcome = []
        worker = Thread(
            target=lambda: outcome.append(
                put_result_frame(result_queue, object(), quit_event)
            )
        )
        worker.start()
        self.assertTrue(worker.is_alive())

        quit_event.set()
        worker.join(timeout=0.3)

        self.assertFalse(worker.is_alive())
        self.assertEqual(outcome, [False])


class MuseTalkResultQueuePolicyTests(unittest.TestCase):
    @staticmethod
    def _idle_result(index):
        idle_audio = [
            (np.zeros(320, dtype=np.float32), 1, None),
            (np.zeros(320, dtype=np.float32), 1, None),
        ]
        return (None, index, idle_audio)

    def test_full_idle_queue_does_not_block_the_inference_thread(self):
        from src.avatars.musetalk.avatar import put_result_frame

        result_queue = queue.Queue(maxsize=1)
        result_queue.put(self._idle_result(0))
        quit_event = Event()
        outcome = []
        worker = Thread(
            target=lambda: outcome.append(
                put_result_frame(result_queue, self._idle_result(1), quit_event)
            )
        )

        worker.start()
        worker.join(timeout=0.2)
        if worker.is_alive():
            quit_event.set()
            worker.join(timeout=0.3)

        self.assertFalse(worker.is_alive())
        self.assertEqual(outcome, [True])
        self.assertEqual(result_queue.qsize(), 1)

    def test_first_speech_result_does_not_wait_behind_idle_backlog(self):
        from src.avatars.musetalk.avatar import put_result_frame

        result_queue = queue.Queue(maxsize=16)
        for index in range(12):
            result_queue.put(self._idle_result(index))

        speech_event = {
            "turn_id": "turn-1",
            "generation": 1,
            "fragment_sequence": 0,
            "media_sequence": 0,
            "status": "start",
        }
        speech_audio = [
            (np.ones(320, dtype=np.float32) * 0.1, 0, speech_event),
            (np.ones(320, dtype=np.float32) * 0.1, 0, speech_event),
        ]

        accepted = put_result_frame(
            result_queue,
            (object(), 12, speech_audio),
            Event(),
        )

        self.assertTrue(accepted)
        self.assertEqual(result_queue.qsize(), 1)
        queued = result_queue.get_nowait()
        self.assertEqual(queued[2], speech_audio)


class MuseTalkIdleContinuityTests(unittest.TestCase):
    def test_dropped_idle_surplus_does_not_skip_source_frames(self):
        """Idle rendering outruns the 25 fps consumer. The surplus silent pairs
        may be dropped, but the frames that do play must stay consecutive;
        skipping indices made idle motion visibly stutter."""
        from src.avatars.musetalk.avatar import inference

        batch_size = 4
        quit_event = Event()
        result_queue = queue.Queue(maxsize=3)
        delivered = []
        audio_out_queue = queue.Queue()
        for _ in range(batch_size * 2 * 2):
            audio_out_queue.put((np.zeros(320, dtype=np.float32), 1, None))

        class FeatureQueue:
            calls = 0

            def get(self, block=True, timeout=None):
                self.calls += 1
                while not result_queue.empty():
                    delivered.append(result_queue.get_nowait()[1])
                if self.calls > 2:
                    quit_event.set()
                    raise queue.Empty
                return [np.zeros(1, dtype=np.float32)] * batch_size

        inference(
            quit_event,
            batch_size,
            [None] * 20,
            FeatureQueue(),
            audio_out_queue,
            result_queue,
            None,
            None,
            None,
            None,
        )

        self.assertEqual(delivered, [0, 1, 2, 3, 4, 5])


class MuseTalkSpeechOnsetTests(unittest.TestCase):
    def test_mixed_batch_keeps_leading_silent_pair_idle(self):
        import torch

        from src.avatars.musetalk.avatar import inference

        quit_event = Event()
        audio_feat_queue = queue.Queue()
        audio_out_queue = queue.Queue()

        audio_feat_queue.put([np.zeros(1, dtype=np.float32) for _ in range(2)])
        # Edge keeps a short natural pause before the first active sample.  All
        # four frames belong to TTS (type 0), but only the second video pair is
        # audible and should receive a generated mouth frame.
        for amplitude in (0.0, 0.0, 0.1, 0.1):
            audio_out_queue.put(
                (np.full(320, amplitude, dtype=np.float32), 0, None)
            )

        class ResultQueue(queue.Queue):
            def put(self, item, block=True, timeout=None):
                super().put(item, block=block, timeout=timeout)
                if self.qsize() == 2:
                    quit_event.set()

        class FakeModel:
            dtype = torch.float32

            def __call__(self, latent_batch, _timesteps, **_kwargs):
                return SimpleNamespace(sample=latent_batch)

        class FakeVAE:
            @staticmethod
            def decode_latents(_pred_latents):
                return ["mouth-0", "mouth-1"]

        result_queue = ResultQueue()
        inference(
            quit_event,
            2,
            [torch.zeros((1, 1), dtype=torch.float32)],
            audio_feat_queue,
            audio_out_queue,
            result_queue,
            FakeVAE(),
            SimpleNamespace(device=torch.device("cpu"), model=FakeModel()),
            lambda value: value,
            torch.tensor([0]),
        )

        results = [result_queue.get_nowait() for _ in range(2)]
        self.assertEqual([item[0] for item in results], [None, "mouth-1"])
        self.assertEqual(
            [[frame_type for _, frame_type, _ in item[2]] for item in results],
            [[1, 1], [0, 0]],
        )


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
        from src.server.reply_streaming.channel import PlayableFragment
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
        from src.server.reply_streaming.channel import PlayableFragment
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
        from src.server.reply_streaming.channel import PlayableFragment
        from src.server.reply_streaming.retry import RetryBudget
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


if __name__ == "__main__":
    unittest.main()
