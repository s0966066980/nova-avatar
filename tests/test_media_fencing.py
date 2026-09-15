import asyncio
import queue
import unittest
from fractions import Fraction
from types import SimpleNamespace

import numpy as np


class MuseTalkEnvelopePropagationTests(unittest.TestCase):
    def test_flush_clears_every_musetalk_stage_queue(self):
        from src.avatars.audio_stream_handler import BaseAudioStreamHandler

        config = SimpleNamespace(
            audio=SimpleNamespace(fps=50, l=0, r=0),
            model=SimpleNamespace(batch_size=1),
        )
        handler = BaseAudioStreamHandler(config)
        handler.output_queue = queue.Queue()
        handler.feat_queue = queue.Queue()
        handler.put_audio_frame(np.ones(320, dtype=np.float32), {})
        handler.output_queue.put(object())
        handler.feat_queue.put(object())
        handler.frames.append(np.ones(320, dtype=np.float32))

        handler.flush_talk()

        self.assertTrue(handler.queue.empty())
        self.assertTrue(handler.output_queue.empty())
        self.assertTrue(handler.feat_queue.empty())
        self.assertEqual(handler.frames, [])

    def test_avatar_flush_clears_completed_gpu_results(self):
        from src.avatars.base import BaseAvatar

        class Flushable:
            def __init__(self):
                self.flush_count = 0

            def flush_talk(self):
                self.flush_count += 1

        avatar = BaseAvatar.__new__(BaseAvatar)
        avatar.tts = Flushable()
        avatar.audio_stream = Flushable()
        avatar.res_frame_queue = queue.Queue()
        avatar.res_frame_queue.put(object())
        avatar.configure_media_fence(
            media_guard=lambda _event, _stage: True,
            on_stale_drop=lambda _stage, _reason: None,
        )
        avatar._media_sequences[("turn-1", 1)] = 9

        avatar.flush_talk()

        self.assertTrue(avatar.res_frame_queue.empty())
        self.assertEqual(avatar._media_sequences, {})
        self.assertEqual(avatar.tts.flush_count, 1)
        self.assertEqual(avatar.audio_stream.flush_count, 1)

    def test_avatar_assigns_one_monotonic_media_sequence_across_fragments(self):
        from src.avatars.base import BaseAvatar

        class AudioStream:
            def __init__(self):
                self.items = []

            def put_audio_frame(self, frame, eventpoint):
                self.items.append((frame, eventpoint))
                return True

        avatar = BaseAvatar.__new__(BaseAvatar)
        avatar.audio_stream = AudioStream()
        avatar.configure_media_fence(
            media_guard=lambda _event, _stage: True,
            on_stale_drop=lambda _stage, _reason: None,
        )
        for fragment_sequence in (4, 5):
            avatar.put_audio_frame(
                np.ones(320, dtype=np.float32),
                {
                    "turn_id": "turn-1",
                    "generation": 6,
                    "fragment_sequence": fragment_sequence,
                    "media_sequence": 0,
                },
            )

        events = [event for _frame, event in avatar.audio_stream.items]
        self.assertEqual([event["media_sequence"] for event in events], [0, 1])
        self.assertEqual(
            [event["fragment_media_sequence"] for event in events],
            [0, 0],
        )
        self.assertEqual(
            [event["fragment_sequence"] for event in events],
            [4, 5],
        )

    def test_audio_stream_rechecks_generation_after_dequeue(self):
        from src.avatars.audio_stream_handler import BaseAudioStreamHandler

        valid = [True]
        stale_drops = []

        class Parent:
            @staticmethod
            def accepts_media(eventpoint, _stage):
                return not eventpoint.get("turn_id") or valid[0]

            @staticmethod
            def record_stale_drop(stage, reason):
                stale_drops.append((stage, reason))

        config = SimpleNamespace(
            audio=SimpleNamespace(fps=50, l=0, r=0),
            model=SimpleNamespace(batch_size=1),
        )
        handler = BaseAudioStreamHandler(config, Parent())
        eventpoint = {
            "turn_id": "turn-1",
            "generation": 1,
            "fragment_sequence": 0,
            "media_sequence": 0,
        }
        handler.put_audio_frame(np.ones(320, dtype=np.float32), eventpoint)
        valid[0] = False

        frame, frame_type, committed_event = handler.get_audio_frame()

        self.assertTrue(np.array_equal(frame, np.zeros(320, dtype=np.float32)))
        self.assertEqual(frame_type, 1)
        self.assertIsNone(committed_event)
        self.assertEqual(stale_drops, [("avatar_audio_consume", "stale_generation")])
        handler.put_audio_frame(np.ones(320, dtype=np.float32), eventpoint)
        self.assertTrue(handler.queue.empty())
        self.assertEqual(
            stale_drops,
            [
                ("avatar_audio_consume", "stale_generation"),
                ("avatar_audio_enqueue", "stale_generation"),
            ],
        )


    def test_feature_batch_preserves_paired_audio_envelopes(self):
        from src.avatars.musetalk.audio_stream_handler import (
            MuseAudioStreamHandler,
            MuseInferenceBatch,
        )

        class AudioProcessor:
            @staticmethod
            def audio2feat(_samples):
                return np.zeros((1, 1), dtype=np.float32)

            @staticmethod
            def feature2chunks(**_kwargs):
                return [np.zeros((1, 1), dtype=np.float32)]

        config = SimpleNamespace(
            audio=SimpleNamespace(fps=50, l=0, r=0),
            model=SimpleNamespace(batch_size=1),
        )
        handler = MuseAudioStreamHandler(config, None, AudioProcessor())
        self.assertEqual(handler.queue.maxsize, 100)
        handler.feat_queue = queue.Queue()
        handler.output_queue = queue.Queue()
        envelopes = [
            {
                "turn_id": "turn-1",
                "generation": 4,
                "fragment_sequence": 2,
                "media_sequence": sequence,
            }
            for sequence in (8, 9)
        ]
        for envelope in envelopes:
            handler.put_audio_frame(np.ones(320, dtype=np.float32), envelope)

        handler.run_step()

        batch = handler.feat_queue.get_nowait()
        self.assertIsInstance(batch, MuseInferenceBatch)
        self.assertEqual(
            [event for _frame, _frame_type, event in batch.audio_frames],
            envelopes,
        )
        self.assertTrue(handler.output_queue.empty())

    def test_first_feature_batch_uses_startup_microbatch(self):
        from src.avatars.musetalk.audio_stream_handler import MuseAudioStreamHandler

        seen_batch_sizes = []

        class AudioProcessor:
            @staticmethod
            def audio2feat(_samples):
                return np.zeros((1, 1), dtype=np.float32)

            @staticmethod
            def feature2chunks(**kwargs):
                seen_batch_sizes.append(kwargs["batch_size"])
                return [np.zeros((1, 1), dtype=np.float32)] * kwargs["batch_size"]

        config = SimpleNamespace(
            audio=SimpleNamespace(fps=50, l=0, r=0),
            model=SimpleNamespace(batch_size=8),
        )
        handler = MuseAudioStreamHandler(config, None, AudioProcessor())
        handler.feat_queue = queue.Queue()
        for _ in range(handler.startup_batch_size * 2):
            handler.put_audio_frame(np.ones(320, dtype=np.float32), {})

        handler.run_step()

        batch = handler.feat_queue.get_nowait()
        self.assertEqual(handler.startup_batch_size, 4)
        self.assertEqual(batch.batch_size, 4)
        self.assertEqual(seen_batch_sizes, [4])
        self.assertTrue(handler.startup_batch_emitted)

    def test_idle_batch_skips_whisper_feature_extraction(self):
        from src.avatars.musetalk.audio_stream_handler import MuseAudioStreamHandler

        class AudioProcessor:
            @staticmethod
            def audio2feat(_samples):
                raise AssertionError("idle batch must not call audio2feat")

            @staticmethod
            def feature2chunks(**_kwargs):
                raise AssertionError("idle batch must not create feature chunks")

        config = SimpleNamespace(
            audio=SimpleNamespace(fps=50, l=0, r=0),
            model=SimpleNamespace(batch_size=2),
        )
        handler = MuseAudioStreamHandler(config, None, AudioProcessor())
        handler.feat_queue = queue.Queue()
        for _ in range(handler.startup_batch_size * 2):
            handler.queue.put((np.zeros(320, dtype=np.float32), {}))

        handler.run_step()

        batch = handler.feat_queue.get_nowait()
        self.assertEqual(batch.features, ())
        self.assertEqual(len(batch.audio_frames), 4)

    def test_full_audio_queue_rechecks_generation_after_interrupt_flush(self):
        from threading import Thread

        from src.avatars.musetalk.audio_stream_handler import MuseAudioStreamHandler

        valid = [True]

        class Parent:
            curr_state = 0

            @staticmethod
            def accepts_media(_eventpoint, _stage):
                return valid[0]

            @staticmethod
            def record_stale_drop(_stage, _reason):
                return None

        config = SimpleNamespace(
            audio=SimpleNamespace(fps=50, l=0, r=0),
            model=SimpleNamespace(batch_size=1),
        )
        handler = MuseAudioStreamHandler(config, Parent(), object())
        for _ in range(handler.queue.maxsize):
            handler.queue.put((np.zeros(320, dtype=np.float32), {}))
        eventpoint = {
            "turn_id": "turn-1",
            "generation": 1,
            "fragment_sequence": 0,
            "media_sequence": 0,
        }
        outcome = []
        producer = Thread(
            target=lambda: outcome.append(
                handler.put_audio_frame(
                    np.ones(320, dtype=np.float32),
                    eventpoint,
                )
            )
        )
        producer.start()
        self.assertTrue(producer.is_alive())

        valid[0] = False
        handler.flush_talk()
        producer.join(timeout=0.3)

        self.assertFalse(producer.is_alive())
        self.assertEqual(outcome, [False])
        self.assertTrue(handler.queue.empty())

    def test_cancelled_batch_is_rejected_before_gpu_inference(self):
        import torch

        from src.avatars.musetalk.audio_stream_handler import MuseInferenceBatch
        from src.avatars.musetalk.avatar import inference

        quit_event = __import__("threading").Event()
        envelope = {
            "turn_id": "cancelled-turn",
            "generation": 2,
            "fragment_sequence": 0,
            "media_sequence": 0,
        }
        batch = MuseInferenceBatch(
            features=[np.zeros((1, 1), dtype=np.float32)],
            audio_frames=tuple(
                (np.ones(320, dtype=np.float32), 0, dict(envelope))
                for _ in range(2)
            ),
        )

        class FeatureQueue:
            @staticmethod
            def get(**_kwargs):
                quit_event.set()
                return batch

        class MustNotRun:
            def __getattr__(self, name):
                raise AssertionError(f"stale batch reached GPU boundary: {name}")

        stale_drops = []

        result_queue = queue.Queue()

        inference(
            quit_event,
            1,
            [torch.zeros((1, 1), dtype=torch.float32)],
            FeatureQueue(),
            queue.Queue(),
            result_queue,
            MustNotRun(),
            MustNotRun(),
            MustNotRun(),
            torch.tensor([0]),
            media_guard=lambda _event, _stage: False,
            on_stale_drop=lambda stage, reason: stale_drops.append((stage, reason)),
        )

        self.assertTrue(result_queue.empty())
        self.assertEqual(stale_drops, [("musetalk_batch", "stale_generation")])

    def test_batch_cancelled_during_gpu_inference_cannot_publish_results(self):
        import torch

        from src.avatars.musetalk.audio_stream_handler import MuseInferenceBatch
        from src.avatars.musetalk.avatar import inference

        quit_event = __import__("threading").Event()
        valid = [True]
        envelope = {
            "turn_id": "turn-1",
            "generation": 3,
            "fragment_sequence": 1,
            "media_sequence": 4,
        }
        batch = MuseInferenceBatch(
            features=[np.zeros((1, 1), dtype=np.float32)],
            audio_frames=tuple(
                (np.ones(320, dtype=np.float32), 0, dict(envelope))
                for _ in range(2)
            ),
        )

        class FeatureQueue:
            @staticmethod
            def get(**_kwargs):
                return batch

        class FakeModel:
            dtype = torch.float32

            @staticmethod
            def __call__(latent_batch, _timesteps, **_kwargs):
                valid[0] = False
                return SimpleNamespace(sample=latent_batch)

        class FakeVAE:
            @staticmethod
            def decode_latents(_latents):
                return ["stale-mouth-frame"]

        stale_drops = []

        class ResultQueue(queue.Queue):
            def put(self, item, block=True, timeout=None):
                super().put(item, block=block, timeout=timeout)
                quit_event.set()

        result_queue = ResultQueue()

        def record_stale_drop(stage, reason):
            stale_drops.append((stage, reason))
            quit_event.set()

        inference(
            quit_event,
            1,
            [torch.zeros((1, 1), dtype=torch.float32)],
            FeatureQueue(),
            queue.Queue(),
            result_queue,
            FakeVAE(),
            SimpleNamespace(device=torch.device("cpu"), model=FakeModel()),
            lambda value: value,
            torch.tensor([0]),
            media_guard=lambda _event, _stage: valid[0],
            on_stale_drop=record_stale_drop,
        )

        self.assertTrue(result_queue.empty())
        self.assertEqual(stale_drops, [("musetalk_result", "stale_generation")])


class DirectAudioFanoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_streaming_keeps_validated_coupled_audio_clock_by_default(self):
        from src.server.voice_session import VoiceTurnSession

        configured = []

        class Avatar:
            @staticmethod
            def configure_audio_output(track, loop):
                configured.append((track, loop))

        player = SimpleNamespace(audio=object())
        session = VoiceTurnSession.__new__(VoiceTurnSession)
        session.avatar = Avatar()
        session.config = SimpleNamespace(
            reply_streaming=SimpleNamespace(
                enabled=True,
                decoupled_audio_clock=False,
            )
        )

        session.attach_media_player(player)

        self.assertIs(session._media_player, player)
        self.assertEqual(configured, [])

    async def test_decoupled_audio_clock_can_only_be_enabled_explicitly(self):
        from src.server.voice_session import VoiceTurnSession

        configured = []

        class Avatar:
            @staticmethod
            def configure_audio_output(track, loop):
                configured.append((track, loop))

        player = SimpleNamespace(audio=object())
        session = VoiceTurnSession.__new__(VoiceTurnSession)
        session.avatar = Avatar()
        session.config = SimpleNamespace(
            reply_streaming=SimpleNamespace(
                enabled=True,
                decoupled_audio_clock=True,
            )
        )

        session.attach_media_player(player)

        self.assertEqual(len(configured), 1)
        self.assertIs(configured[0][0], player.audio)
        self.assertIs(configured[0][1], asyncio.get_running_loop())

    async def test_tts_pcm_is_fanned_out_before_avatar_result(self):
        from src.avatars.base import BaseAvatar

        class AudioStream:
            def __init__(self):
                self.items = []

            def put_audio_frame(self, frame, eventpoint):
                self.items.append((frame, eventpoint))
                return True

        class Track:
            def __init__(self):
                self.items = []

            async def prepare_speech_start(self):
                self.items.append(("prepared", None))

            async def enqueue(self, frame, eventpoint):
                self.items.append((frame, eventpoint))

        avatar = BaseAvatar.__new__(BaseAvatar)
        avatar.audio_stream = AudioStream()
        avatar.recording = False
        avatar.configure_media_fence(
            media_guard=lambda _event, _stage: True,
            on_stale_drop=lambda _stage, _reason: None,
        )
        track = Track()
        avatar.configure_audio_output(track, asyncio.get_running_loop())
        eventpoint = {
            "turn_id": "turn-1",
            "generation": 1,
            "fragment_sequence": 0,
            "status": "start",
        }

        accepted = await asyncio.to_thread(
            avatar.put_audio_frame,
            np.ones(320, dtype=np.float32) * 0.1,
            eventpoint,
        )

        self.assertTrue(accepted)
        self.assertEqual(len(avatar.audio_stream.items), 1)
        self.assertEqual(track.items[0][0], "prepared")
        self.assertEqual(len(track.items), 2)
        self.assertEqual(track.items[1][1]["status"], "start")


class WebRTCMediaFenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_video_drops_oldest_frame_without_blocking_audio_path(self):
        from src.utils.webrtc import HumanPlayer

        drops = []
        player = HumanPlayer(
            None,
            on_stale_drop=lambda stage, reason: drops.append((stage, reason)),
        )
        video = player.video
        originals = [object() for _ in range(video.max_buffer_frames)]
        for frame in originals:
            await video.enqueue(frame)
        newest = object()

        accepted = await asyncio.wait_for(video.enqueue(newest), timeout=0.05)

        self.assertTrue(accepted)
        self.assertEqual(video._queue.qsize(), video.max_buffer_frames)
        queued_frames = [item[0] for item in video._queue._queue]
        self.assertNotIn(originals[0], queued_frames)
        self.assertIs(queued_frames[-1], newest)
        self.assertEqual(drops, [("webrtc_video", "late_video")])
        player.audio.stop()
        player.video.stop()

    async def test_video_repeats_last_valid_frame_when_gpu_is_late(self):
        from src.utils.webrtc import PlayerStreamTrack

        class Player:
            @staticmethod
            def _start(_track):
                return None

            @staticmethod
            def _stop(_track):
                return None

            @staticmethod
            def notify(_eventpoint):
                return None

            @staticmethod
            def notify_media_timing(_kind, _seconds, _eventpoint=None):
                return None

        frame = SimpleNamespace(pts=None, time_base=None)
        track = PlayerStreamTrack(Player(), kind="video")
        await track.enqueue(frame)

        first = await track.recv()
        repeated = await asyncio.wait_for(track.recv(), timeout=0.15)

        self.assertIs(first, frame)
        self.assertIs(repeated, frame)
        track.stop()

    async def test_video_stall_cannot_rebase_the_audio_master_clock(self):
        from unittest.mock import AsyncMock, patch

        from src.utils.webrtc import HumanPlayer

        now = [100.0]
        player = HumanPlayer(None)
        with (
            patch("src.utils.webrtc.time.monotonic", side_effect=lambda: now[0]),
            patch("src.utils.webrtc.asyncio.sleep", new=AsyncMock()),
            patch("src.utils.webrtc.mylogger"),
        ):
            await player.audio.next_timestamp()
            await player.video.next_timestamp()
            audio_clock_start = player.audio._start
            now[0] += 1.0
            await player.video.next_timestamp()

        self.assertEqual(player.audio._start, audio_clock_start)
        player.audio.stop()
        player.video.stop()

    async def test_interrupt_drain_removes_only_stale_outbound_media(self):
        from src.utils.webrtc import HumanPlayer

        generation = [1]
        stale_drops = []

        def media_guard(eventpoint, _stage):
            return eventpoint["generation"] == generation[0]

        player = HumanPlayer(
            None,
            media_guard=media_guard,
            on_stale_drop=lambda stage, reason: stale_drops.append((stage, reason)),
        )
        old_event = {
            "turn_id": "turn-1",
            "generation": 1,
            "fragment_sequence": 0,
            "media_sequence": 0,
        }
        await player.audio.enqueue(object(), old_event)
        await player.video.enqueue(object(), old_event)
        generation[0] = 2

        discarded = player.discard_stale_media()

        self.assertEqual(discarded, {"audio": 1, "video": 1})
        self.assertEqual(player.audio.buffered_duration, 0.0)
        self.assertEqual(player.video.buffered_duration, 0.0)
        self.assertEqual(
            stale_drops,
            [
                ("webrtc_audio", "stale_generation"),
                ("webrtc_video", "stale_generation"),
            ],
        )
        player.audio.stop()
        player.video.stop()

    async def test_renderer_drops_stale_result_and_pairs_video_with_audio_envelope(self):
        from threading import Event

        from src.avatars.base import BaseAvatar

        current_generation = [2]
        stale_drops = []
        quit_event = Event()

        class Track:
            def __init__(self, kind):
                self.kind = kind
                self.items = []

            async def enqueue(self, frame, eventpoint=None):
                self.items.append((frame, eventpoint))
                if (
                    self.kind == "audio"
                    and eventpoint
                    and eventpoint["generation"] == 2
                    and len(
                        [
                            item
                            for item in self.items
                            if item[1] and item[1]["generation"] == 2
                        ]
                    ) == 2
                ):
                    quit_event.set()
                return True

        def event(generation, sequence):
            return {
                "turn_id": "turn-1",
                "generation": generation,
                "fragment_sequence": 0,
                "media_sequence": sequence,
            }

        avatar = BaseAvatar.__new__(BaseAvatar)
        avatar.config = SimpleNamespace(sessionid=7)
        avatar.res_frame_queue = queue.Queue()
        avatar.frame_list_cycle = [np.zeros((8, 8, 3), dtype=np.uint8)]
        avatar.custom_index = {}
        avatar.custom_img_cycle = {}
        avatar.speaking = False
        avatar.record_video_data = lambda _frame: None
        avatar.record_audio_data = lambda _frame: None
        avatar.paste_back_frame = lambda _frame, _index: np.zeros(
            (8, 8, 3), dtype=np.uint8
        )
        avatar.configure_media_fence(
            media_guard=lambda eventpoint, _stage: (
                eventpoint["generation"] == current_generation[0]
            ),
            on_stale_drop=lambda stage, reason: stale_drops.append((stage, reason)),
        )
        for generation in (1, 2):
            audio_frames = [
                (
                    np.full(
                        320,
                        (sequence + 1) / 10,
                        dtype=np.float32,
                    ),
                    0,
                    event(generation, sequence),
                )
                for sequence in (0, 1)
            ]
            avatar.res_frame_queue.put(("mouth", 0, audio_frames))

        audio_track = Track("audio")
        video_track = Track("video")
        await asyncio.wait_for(
            asyncio.to_thread(
                avatar.process_frames,
                quit_event,
                asyncio.get_running_loop(),
                audio_track,
                video_track,
            ),
            timeout=1,
        )

        self.assertEqual(
            [item[1]["generation"] for item in audio_track.items],
            [2, 2],
        )
        self.assertEqual(
            [item[1]["media_sequence"] for item in audio_track.items],
            [0, 1],
        )
        self.assertEqual(
            [item[0].sample_rate for item in audio_track.items],
            [16000, 16000],
        )
        self.assertEqual(
            [item[0].samples for item in audio_track.items],
            [320, 320],
        )
        self.assertEqual(
            [int(item[0].to_ndarray().reshape(-1)[0]) for item in audio_track.items],
            [3276, 6553],
        )
        self.assertEqual(
            [item[1]["generation"] for item in video_track.items],
            [2],
        )
        self.assertEqual(video_track.items[0][1]["media_sequence"], 0)
        self.assertEqual(
            stale_drops,
            [("musetalk_result_consume", "stale_generation")],
        )

    async def test_renderer_keeps_mouth_continuous_when_result_is_followed_by_idle(self):
        """The real renderer seam must mask-only blend a speech/idle boundary."""
        from threading import Event

        from src.avatars.base import BaseAvatar
        from src.avatars.musetalk.mouth_continuity import MouthContinuityController

        quit_event = Event()

        class Track:
            def __init__(self, kind):
                self.kind = kind
                self.items = []

            async def enqueue(self, frame, eventpoint=None):
                self.items.append((frame, eventpoint))
                if self.kind == "video" and len(self.items) >= 2:
                    quit_event.set()
                return True

        eventpoint = {
            "turn_id": "turn-1",
            "generation": 1,
            "fragment_sequence": 0,
            "media_sequence": 0,
        }
        source = np.zeros((8, 8, 3), dtype=np.uint8)
        mask = np.zeros((8, 8), dtype=np.uint8)
        mask[2:6, 2:6] = 255
        generated = np.full((8, 8, 3), 200, dtype=np.uint8)

        avatar = BaseAvatar.__new__(BaseAvatar)
        avatar.config = SimpleNamespace(sessionid=7)
        avatar.res_frame_queue = queue.Queue()
        avatar.frame_list_cycle = [source]
        avatar.custom_index = {}
        avatar.custom_img_cycle = {}
        avatar.speaking = False
        avatar._direct_audio_track = None
        avatar._direct_audio_loop = None
        avatar.record_video_data = lambda _frame: None
        avatar.record_audio_data = lambda _frame: None
        avatar.paste_back_frame = lambda _frame, _index: generated.copy()
        avatar._mouth_continuity = MouthContinuityController([source], [mask], gap_grace_frames=1)
        avatar.configure_media_fence(
            media_guard=lambda _eventpoint, _stage: True,
            on_stale_drop=lambda _stage, _reason: None,
        )

        speech_audio = [
            (np.ones(320, dtype=np.float32), 0, eventpoint),
            (np.ones(320, dtype=np.float32), 0, eventpoint),
        ]
        idle_audio = [
            (np.zeros(320, dtype=np.float32), 1, None),
            (np.zeros(320, dtype=np.float32), 1, None),
        ]
        avatar.res_frame_queue.put((generated, 0, speech_audio))
        avatar.res_frame_queue.put((source, 0, idle_audio))

        audio_track = Track("audio")
        video_track = Track("video")
        await asyncio.wait_for(
            asyncio.to_thread(
                avatar.process_frames,
                quit_event,
                asyncio.get_running_loop(),
                audio_track,
                video_track,
            ),
            timeout=1,
        )

        self.assertEqual(len(video_track.items), 2)
        first = video_track.items[0][0].to_ndarray()
        second = video_track.items[1][0].to_ndarray()
        roi = (slice(2, 6), slice(2, 6))
        self.assertLessEqual(
            abs(float(first[roi].mean()) - float(second[roi].mean())),
            50.0,
        )
        self.assertEqual(int(second[0, 0].mean()), 0)

    async def test_commit_boundary_skips_queued_frame_after_generation_changes(self):
        from src.utils.webrtc import PlayerStreamTrack

        generation = [1]
        stale_drops = []

        class Player:
            @staticmethod
            def _start(_track):
                return None

            @staticmethod
            def _stop(_track):
                return None

            @staticmethod
            def notify(_eventpoint):
                return None

            @staticmethod
            def notify_media_timing(_kind, _seconds, _eventpoint=None):
                return None

            @staticmethod
            def notify_audio_activity(_active):
                return None

        def event(frame_generation):
            return {
                "turn_id": "turn-1",
                "generation": frame_generation,
                "fragment_sequence": 0,
                "media_sequence": frame_generation,
            }

        def media_guard(eventpoint, _stage):
            return eventpoint["generation"] == generation[0]

        def frame(name):
            return SimpleNamespace(
                name=name,
                pts=None,
                time_base=None,
                to_ndarray=lambda: np.ones((1, 320), dtype=np.int16),
            )

        track = PlayerStreamTrack(
            Player(),
            kind="audio",
            media_guard=media_guard,
            on_stale_drop=lambda stage, reason: stale_drops.append((stage, reason)),
        )
        old_frame = frame("old")
        fresh_frame = frame("fresh")
        await track.enqueue(old_frame, event(1))
        generation[0] = 2
        await track.enqueue(fresh_frame, event(2))

        committed = await track.recv()

        self.assertIs(committed, fresh_frame)
        self.assertEqual(stale_drops, [("webrtc_audio", "stale_generation")])
        track.stop()

    async def test_commit_boundary_rechecks_generation_after_pacing(self):
        from src.utils.webrtc import PlayerStreamTrack

        generation = [1]
        callbacks = []

        class Player:
            _start = staticmethod(lambda _track: None)
            _stop = staticmethod(lambda _track: None)
            notify = staticmethod(lambda _eventpoint: None)
            notify_media_timing = staticmethod(
                lambda _kind, _seconds, _eventpoint=None: None
            )
            notify_audio_activity = staticmethod(lambda _active: None)
            notify_audio_frame = staticmethod(
                lambda eventpoint, _active: callbacks.append(eventpoint["generation"])
            )

        def event(value):
            return {"turn_id": "turn-1", "generation": value, "media_sequence": value}

        def frame():
            return SimpleNamespace(
                pts=None,
                time_base=None,
                to_ndarray=lambda: np.ones((1, 320), dtype=np.int16),
            )

        track = PlayerStreamTrack(
            Player(),
            kind="audio",
            media_guard=lambda item, _stage: item["generation"] == generation[0],
        )
        track._drift_logged_at = float("inf")
        old_frame, fresh_frame = frame(), frame()
        await track.enqueue(old_frame, event(1))
        calls = 0

        async def pace():
            nonlocal calls
            calls += 1
            if calls == 1:
                generation[0] = 2
                await track.enqueue(fresh_frame, event(2))
            return calls * 320, Fraction(1, 16000)

        track.next_timestamp = pace

        self.assertIs(await track.recv(), fresh_frame)
        self.assertEqual(callbacks, [2])
        track.stop()


if __name__ == "__main__":
    unittest.main()
