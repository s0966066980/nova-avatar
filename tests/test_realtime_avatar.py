# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Renderer and RTP regressions shared by x86 and Jetson."""
import asyncio
import time
from types import SimpleNamespace

import numpy as np
import pytest
from av import AudioFrame, VideoFrame

from src.utils.webrtc import HumanPlayer


def test_first_speech_after_interrupt_keeps_feature_and_pcm_centers_aligned():
    from src.avatars.musetalk.audio_stream_handler import MuseAudioStreamHandler

    class Features:
        def audio2feat(self, samples):
            return samples.reshape(-1, 320)[:, 0]

        def feature2chunks(self, *, feature_array, fps, batch_size, start):
            return [feature_array[int((start + i) * 2)] for i in range(batch_size)]

    config = SimpleNamespace(model=SimpleNamespace(batch_size=8),
                             audio=SimpleNamespace(fps=50, l=10, r=10, av_offset_ms=0))
    handler = MuseAudioStreamHandler(config, None, Features())
    handler.warm_up()
    handler.run_step()
    handler.feat_queue.get_nowait()
    handler.flush_talk()
    for sequence in range(32):
        handler.queue.put((np.full(320, (sequence + 1) / 100, np.float32),
                           {'turn_id': 'new', 'generation': 1, 'media_sequence': sequence}))
    handler.run_step()
    assert not handler.feat_queue.empty(), 'first reply waited for lost feature context'
    batch = handler.feat_queue.get_nowait()
    assert [event['media_sequence'] for _, _, event in batch.audio_frames] == list(range(8))
    assert batch.features == pytest.approx([frame[0] for frame, _, _ in batch.audio_frames[::2]])


def test_interrupt_during_whisper_cannot_publish_or_restore_old_context():
    from src.avatars.musetalk.audio_stream_handler import MuseAudioStreamHandler

    class Features:
        interrupt = True

        def audio2feat(self, samples):
            if self.interrupt:
                self.interrupt = False
                handler.flush_talk()
            return samples.reshape(-1, 320)[:, 0]

        def feature2chunks(self, *, feature_array, fps, batch_size, start):
            return [feature_array[int((start + i) * 2)] for i in range(batch_size)]

    config = SimpleNamespace(model=SimpleNamespace(batch_size=8),
                             audio=SimpleNamespace(fps=50, l=10, r=10, av_offset_ms=0))
    handler = MuseAudioStreamHandler(config, None, Features())
    handler.warm_up()
    for generation in (0, 1):
        for sequence in range(32):
            handler.queue.put((np.full(320, (sequence + 1) / 100, np.float32),
                               {'turn_id': str(generation), 'generation': generation,
                                'media_sequence': sequence}))
        handler.run_step()
        if generation == 0:
            assert handler.feat_queue.empty()
            assert not handler.startup_batch_emitted
        else:
            batch = handler.feat_queue.get_nowait()
            assert all(event['generation'] == 1 for _, _, event in batch.audio_frames)
            assert batch.features == pytest.approx(
                [frame[0] for frame, _, _ in batch.audio_frames[::2]])


def test_interrupt_releases_a_batch_waiting_for_feature_queue_space(monkeypatch):
    import queue
    from threading import Event, Thread
    from src.avatars.musetalk.audio_stream_handler import MuseAudioStreamHandler

    config = SimpleNamespace(model=SimpleNamespace(batch_size=1),
                             audio=SimpleNamespace(fps=50, l=0, r=0, av_offset_ms=0))
    handler = MuseAudioStreamHandler(config, None, object())
    handler.quit_event = Event()
    for _ in range(handler.feat_queue.maxsize):
        handler.feat_queue.put_nowait(object())
    blocked = Event()
    put = handler.feat_queue.put_nowait

    def put_when_full(batch):
        try:
            put(batch)
        except queue.Full:
            blocked.set()
            raise

    monkeypatch.setattr(handler.feat_queue, 'put_nowait', put_when_full)
    results = []
    worker = Thread(target=lambda: results.append(handler.run_step()))
    worker.start()
    try:
        assert blocked.wait(timeout=1)
        handler.flush_talk()
        worker.join(timeout=1)
        assert not worker.is_alive()
        assert results == [False]
        assert handler.feat_queue.empty()
        assert not handler.startup_batch_emitted
    finally:
        handler.quit_event.set()
        worker.join(timeout=1)

def audio_frame(active=False):
    frame = AudioFrame(format='s16',layout='mono',samples=320)
    frame.planes[0].update((np.full(320,1000 if active else 0,np.int16)).tobytes())
    frame.sample_rate=16000
    return frame


def test_coupled_audio_clock_keeps_advancing_while_renderer_is_busy():
    async def run():
        player=HumanPlayer(None)
        player._start=lambda _track:None
        try:
            async def receive():
                return [await player.audio.recv() for _ in range(5)]
            frames=await asyncio.wait_for(receive(),.25)
            assert [frame.pts for frame in frames]==[0,320,640,960,1280]
            assert all(not np.any(frame.to_ndarray()) for frame in frames)
        finally:
            player.audio.stop();player.video.stop()
    asyncio.run(run())


def test_audio_timeout_uses_remaining_packet_budget_after_encoding(monkeypatch):
    """Missing renderer PCM must not add a fresh 20ms after each encode."""
    async def run():
        now = [100.0]
        releases = []
        player = HumanPlayer(None)
        player._start = lambda _: None

        async def timeout_wait(pending, *, timeout):
            now[0] += timeout
            return set(), set(pending)

        monkeypatch.setattr('src.utils.webrtc.time.monotonic', lambda: now[0])
        monkeypatch.setattr('src.utils.webrtc.asyncio.wait', timeout_wait)
        try:
            for _ in range(20):
                frame = await player.audio.recv()
                assert not np.any(frame.to_ndarray())
                releases.append(now[0])
                now[0] += .008  # Opus processing / event-loop work before recv.
            assert np.max(np.abs(np.diff(releases) - .020)) < .00001
            assert player.audio._pacing_clock.rebase_count == 0
        finally:
            player.audio.stop(); player.video.stop()
    asyncio.run(run())


def test_track_cancellation_is_preserved_when_queue_read_finishes_at_same_time():
    async def run():
        player = HumanPlayer(None)
        player._start = lambda _: None
        original_queue = player.audio._queue
        receiving = None
        class Queue:
            def qsize(self): return 0
            async def get(self):
                receiving.cancel()
                return audio_frame(), None
        player.audio._queue = Queue()
        try:
            receiving = asyncio.create_task(player.audio.recv())
            with pytest.raises(asyncio.CancelledError):
                await receiving
        finally:
            player.audio._queue = original_queue
            player.audio.stop(); player.video.stop()
    asyncio.run(run())


@pytest.mark.parametrize('event', [{}, {'status': 'end'}])
def test_untagged_tts_pause_and_final_pcm_survive_idle_backlog_trimming(event):
    import queue
    from threading import Event
    from src.avatars.musetalk.avatar import put_result_frame

    results = queue.Queue(maxsize=16)
    # Quiet synthesized PCM is normalized to idle mouth shape, but remains
    # part of the spoken timeline even on older, untagged TTS entry points.
    quiet_pair = [(np.zeros(320, np.float32), 1, dict(event)) for _ in range(2)]
    results.put((None, 0, quiet_pair))
    start = {'status': 'start'}
    speech_pair = [(np.ones(320, np.float32) * .1, 0, start) for _ in range(2)]
    assert put_result_frame(results, (object(), 1, speech_pair), Event())
    assert results.qsize() == 2, 'synthesized silence and end marker must not be dropped as idle runway'
    assert results.get_nowait()[2] == quiet_pair


def test_speech_onset_replaces_only_unscoped_idle_lookahead():
    from src.avatars.musetalk.audio_stream_handler import MuseAudioStreamHandler

    feature_inputs = []
    class Features:
        def audio2feat(self, samples):
            feature_inputs.append(samples)
            return np.zeros((36, 5, 384), np.float32)
        def feature2chunks(self, **kwargs): return [kwargs['start']] * kwargs['batch_size']
    config = SimpleNamespace(model=SimpleNamespace(batch_size=8),
                             audio=SimpleNamespace(fps=50, l=10, r=10, av_offset_ms=0))
    parent = SimpleNamespace(tts=SimpleNamespace(has_pending_work=lambda: True))
    handler = MuseAudioStreamHandler(config, parent, Features())
    handler.warm_up()
    handler.run_step()
    handler.feat_queue.get_nowait()  # initial idle microbatch
    for sequence in range(6):
        event = {'turn_id': 'turn', 'media_sequence': sequence}
        if sequence == 0: event['status'] = 'start'
        handler.queue.put((np.full(320, (sequence + 1) / 100, np.float32), event))
    assert handler.run_step() is False
    assert handler.queue.qsize() == 6
    assert handler.feat_queue.empty()
    for sequence in range(6, 32):
        handler.queue.put((np.full(320, (sequence + 1) / 100, np.float32),
                           {'turn_id': 'turn', 'media_sequence': sequence}))
    handler.run_step()
    first = handler.feat_queue.get_nowait()
    assert [event['media_sequence'] for _, _, event in first.audio_frames] == list(range(16))
    handler.run_step()
    second = handler.feat_queue.get_nowait()
    assert [event['media_sequence'] for _, _, event in second.audio_frames] == list(range(16, 32))
    # The first voice sample is centered after the original left context.
    assert np.all(feature_inputs[0][:10 * 320] == 0)
    assert np.allclose(feature_inputs[0][10 * 320:11 * 320], .01)
    assert first.features == [5] * 8


def test_completed_short_utterance_does_not_wait_for_full_lookahead():
    from src.avatars.musetalk.audio_stream_handler import MuseAudioStreamHandler

    class Features:
        def audio2feat(self, _samples): return np.zeros((36, 5, 384), np.float32)
        def feature2chunks(self, **kwargs): return [0] * kwargs['batch_size']
    config = SimpleNamespace(model=SimpleNamespace(batch_size=8),
                             audio=SimpleNamespace(fps=50, l=10, r=10, av_offset_ms=0))
    parent = SimpleNamespace(tts=SimpleNamespace(has_pending_work=lambda: True))
    handler = MuseAudioStreamHandler(config, parent, Features())
    handler.warm_up(); handler.run_step(); handler.feat_queue.get_nowait()
    for sequence in range(6):
        handler.queue.put((np.full(320, .1, np.float32),
                           {'turn_id': 'short', 'media_sequence': sequence,
                            'fragment_end': sequence == 5}))
    assert handler.run_step() is not False
    batch = handler.feat_queue.get_nowait()
    assert [event['media_sequence'] for _, _, event in batch.audio_frames if event] == list(range(6))


@pytest.mark.parametrize('queued_audio,expected_delay', [(32, []), (0, [.192])])
def test_render_throttles_only_idle_when_video_queue_is_full(monkeypatch, queued_audio, expected_delay):
    from threading import Event
    import src.avatars.musetalk.avatar as module

    quit_event = Event()
    delays = []
    class Thread:
        def __init__(self, **_kwargs): pass
        def start(self): pass
        def join(self): pass
    monkeypatch.setattr(module, 'Thread', Thread)
    monkeypatch.setattr(module.time, 'sleep', lambda _seconds: pytest.fail('idle throttle must be wakeable'))
    avatar = module.MuseTalkAvatar.__new__(module.MuseTalkAvatar)
    avatar.batch_size = 8
    avatar.max_tts_audio_wait_seconds = .2
    avatar.init_customindex = lambda: None
    avatar.tts = SimpleNamespace(render=lambda _: None, has_pending_work=lambda: False)
    avatar.audio_stream = SimpleNamespace(
        queue=SimpleNamespace(qsize=lambda: queued_audio, empty=lambda: queued_audio == 0),
        startup_batch_emitted=True, startup_batch_size=4,
        feat_queue=None, output_queue=None, run_step=quit_event.set,
        wait_for_audio=delays.append,
    )
    for name in ('input_latent_list_cycle', 'res_frame_queue', 'vae', 'unet', 'pe', 'timesteps'):
        setattr(avatar, name, None)
    avatar.render(quit_event, video_track=SimpleNamespace(_queue=SimpleNamespace(qsize=lambda: 6)))
    assert delays == pytest.approx(expected_delay)


def test_idle_throttle_wakes_as_soon_as_reply_audio_is_queued():
    import threading
    from src.avatars.musetalk.audio_stream_handler import MuseAudioStreamHandler

    config = SimpleNamespace(model=SimpleNamespace(batch_size=8),
                             audio=SimpleNamespace(fps=50, l=10, r=10, av_offset_ms=0))
    handler = MuseAudioStreamHandler(config, None, None)
    assert handler.wait_for_audio(.01) is False

    pcm = np.full(320, .1, np.float32)
    producer = threading.Timer(.02, handler.put_audio_frame, args=(pcm, {'turn_id': 'turn'}))
    started = time.perf_counter()
    producer.start()
    try:
        # The idle throttle used to sleep ~0.19 s regardless of reply audio.
        assert handler.wait_for_audio(2.0) is True
    finally:
        producer.join()
    assert time.perf_counter() - started < .5
    # Already-queued audio never waits.
    started = time.perf_counter()
    assert handler.wait_for_audio(2.0) is True
    assert time.perf_counter() - started < .1


def test_renderer_gap_does_not_delay_matching_video_after_audio_resumes():
    async def run():
        released={}
        class Player(HumanPlayer):
            def notify_media_timing(self,kind,seconds,event=None):
                if event and event.get('turn_id')=='turn':
                    released.setdefault((kind,event['media_sequence']),time.monotonic())
                super().notify_media_timing(kind,seconds,event)
        player=Player(None)
        player._start=lambda _track:None
        await player.audio.enqueue(audio_frame())
        await player.video.enqueue(VideoFrame.from_ndarray(np.zeros((32,32,3),np.uint8),format='bgr24'))
        async def drain(track):
            while True:await track.recv()
        consumers=[asyncio.create_task(drain(track)) for track in (player.audio,player.video)]
        try:
            # A slow first model batch leaves the renderer with no media.
            await asyncio.sleep(.35)
            for sequence in range(8):
                event={'turn_id':'turn','generation':0,'fragment_sequence':0,'media_sequence':sequence}
                await player.audio.enqueue(audio_frame(True),event)
                if sequence%2==0:
                    await player.video.enqueue(VideoFrame.from_ndarray(np.zeros((32,32,3),np.uint8),format='bgr24'),event)
            async def matched():
                while ('audio',0) not in released or ('video',0) not in released:
                    await asyncio.sleep(.005)
            await asyncio.wait_for(matched(),.6)
            assert abs(released[('video',0)]-released[('audio',0)])<=.08
        finally:
            for task in consumers:task.cancel()
            await asyncio.gather(*consumers,return_exceptions=True)
            player.audio.stop();player.video.stop()
    asyncio.run(run())



def test_paused_uplink_is_drained_without_resampling():
    from unittest.mock import Mock
    from src.config.schema import Config
    from src.server.voice_session import VoiceTurnSession
    from tests.test_voice_session import FakeAvatar

    async def run():
        session = VoiceTurnSession(7, Config(), FakeAvatar())
        resample = Mock()
        session._resample_frame_sync = resample
        session._segmenter = object()
        received = []
        class Track:
            async def recv(self):
                if len(received) == 5:
                    raise EOFError("end of fixture")
                received.append(1)
                return audio_frame()
        try:
            await session._consume_track(Track())
            assert len(received) == 5
            resample.assert_not_called()
        finally:
            await session.close()
    asyncio.run(run())


def test_capture_stays_closed_until_preparation_and_preserves_manual_pause():
    from threading import Event
    from src.config.schema import Config
    from src.server.voice_session import VoiceTurnSession
    from tests.test_voice_session import FakeAvatar

    async def run():
        ready = Event()
        session = VoiceTurnSession(7, Config(), FakeAvatar())
        session._prepare_sync = lambda: ready.wait(timeout=1)
        session.attach_event_sink(lambda _: None)
        task = asyncio.create_task(session.prepare())
        try:
            await asyncio.sleep(0)
            session.handle_control('{"type":"capture","enabled":true}')
            assert not session._gate_open
            session.handle_control('{"type":"capture","enabled":false}')
            ready.set()
            await task
            assert not session._gate_open
            assert session._manual_pause
        finally:
            ready.set()
            await task
            await session.close()
    asyncio.run(run())
