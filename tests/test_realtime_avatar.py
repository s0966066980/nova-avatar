# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Renderer starvation must not stop the authoritative audio timeline."""
import asyncio
import time
from types import SimpleNamespace

import numpy as np
import pytest
import torch
from av import AudioFrame, VideoFrame

from src.utils.webrtc import HumanPlayer


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


def test_tiny_decoder_preserves_scaled_latents_and_original_encoder(monkeypatch):
    from diffusers import AutoencoderTiny
    from src.avatars.musetalk.inference_optimization import TinyVAEDecoder

    seen = []
    class Tiny:
        config = SimpleNamespace(scaling_factor=1.0)
        def to(self, _device): return self
        def eval(self): return self
        def requires_grad_(self, _enabled): return self
        def decode(self, latents):
            seen.append(latents.clone())
            image = torch.zeros((1, 3, 256, 256))
            image[:, 0] = -1
            image[:, 2] = 1
            return SimpleNamespace(sample=image)

    monkeypatch.setattr(AutoencoderTiny, 'from_pretrained', lambda *a, **kw: Tiny())
    original = SimpleNamespace(vae=SimpleNamespace(dtype=torch.float32, device='cpu'), encode='original-encoder')
    decoder = TinyVAEDecoder(original, 'local-model')
    latents = torch.full((1, 4, 32, 32), .18215)
    pixels = decoder.decode_latents(latents)
    assert torch.equal(seen[0], latents)
    assert decoder.encode == 'original-encoder'
    assert pixels.dtype == np.uint8
    assert pixels[0, 0, 0].tolist() == [255, 128, 0]


def test_tiny_decoder_failure_falls_back_without_retrying(monkeypatch):
    from diffusers import AutoencoderTiny
    from src.avatars.musetalk.inference_optimization import TinyVAEDecoder

    attempts = []
    class BrokenTiny:
        config = SimpleNamespace(scaling_factor=1.0)
        def to(self, _device): return self
        def eval(self): return self
        def requires_grad_(self, _enabled): return self
        def decode(self, latents):
            attempts.append(latents)
            raise RuntimeError('decoder failure')
    monkeypatch.setattr(AutoencoderTiny, 'from_pretrained', lambda *a, **kw: BrokenTiny())
    fallback = object()
    original = SimpleNamespace(vae=SimpleNamespace(dtype=torch.float32, device='cpu'), decode_latents=lambda _: fallback)
    decoder = TinyVAEDecoder(original, 'local-model')
    for _ in range(2):
        assert decoder.decode_latents(torch.zeros(1, 4, 32, 32)) is fallback
    assert len(attempts) == 1
    assert decoder._failed


def test_original_and_approximate_decoders_cannot_be_selected_together():
    from src.avatars.musetalk.avatar import load_model

    with pytest.raises(ValueError, match='either'):
        load_model(vae_engine_path='original.engine', tiny_vae_path='local-tiny')


def test_realtime_profile_reaches_production_model_loader(monkeypatch):
    from src.avatars.factory import prepare_avatar_model
    from src.config.loader import load_config
    import src.avatars.musetalk.avatar as module

    selected = []
    model, avatar = object(), object()
    monkeypatch.setattr(module, 'load_model', lambda **options: selected.append(options) or model)
    monkeypatch.setattr(module, 'load_avatar', lambda _: avatar)
    warmed = []
    monkeypatch.setattr(module, 'warm_up', lambda batch, loaded: warmed.append((batch, loaded)))
    monkeypatch.setenv('NOVA_AVATAR_RUNTIME_OVERRIDES_ENABLED', '0')
    config = load_config('config/config_jetson_realtime.yaml')
    assert prepare_avatar_model(config) == (model, avatar)
    assert selected == [{'tiny_vae_path': '.local/jetson/taesd',
                         'unet_engine_path': '.local/jetson/musetalk-unet-fp16.engine'}]
    assert warmed == [(8, model)]
    assert config.video.max_height == 1280
    assert config.llm.provider != 'llamacpp'


def test_default_jetson_profile_accelerates_both_reply_modes(monkeypatch):
    from src.avatars.factory import prepare_avatar_model
    from src.config.loader import load_config
    import src.avatars.musetalk.avatar as module

    selected = []
    model, avatar = object(), object()
    monkeypatch.setattr(module, 'load_model', lambda **options: selected.append(options) or model)
    monkeypatch.setattr(module, 'load_avatar', lambda _: avatar)
    monkeypatch.setattr(module, 'warm_up', lambda *_: None)
    monkeypatch.setenv('NOVA_AVATAR_RUNTIME_OVERRIDES_ENABLED', '0')
    config = load_config('config/config_jetson.yaml')

    assert prepare_avatar_model(config) == (model, avatar)
    assert selected == [{'tiny_vae_path': '.local/jetson/taesd',
                         'unet_engine_path': '.local/jetson/musetalk-unet-fp16.engine'}]
    assert config.video.max_height == 1280
    assert config.llm.provider == 'llamacpp'
    assert config.vad.enabled


def test_diagnostic_profile_can_isolate_saved_llm_preferences(monkeypatch):
    from src.config.loader import load_config
    monkeypatch.setattr('src.config.overrides.load_runtime_overrides',
                        lambda: {'llm': {'provider': 'llamacpp'}})
    monkeypatch.delenv('NOVA_AVATAR_RUNTIME_OVERRIDES_ENABLED', raising=False)
    assert load_config('config/config_jetson_realtime.yaml').llm.provider == 'llamacpp'
    monkeypatch.setenv('NOVA_AVATAR_RUNTIME_OVERRIDES_ENABLED', '0')
    assert load_config('config/config_jetson_realtime.yaml').llm.provider == 'openai'


def test_read_aloud_pauses_capture_and_tags_media_without_calling_llm(monkeypatch):
    from src.config.schema import Config
    from src.server.routes.chat import human
    from src.server.state import state
    from src.server.voice_session import VoiceTurnSession

    async def run():
        messages = []
        events = []
        avatar = SimpleNamespace(
            put_msg_txt=lambda text, data=None: messages.append((text, data)),
            flush_talk=lambda: None,
        )
        config = Config()
        session = VoiceTurnSession(701, config, avatar)
        session.attach_event_sink(lambda raw: events.append(raw))
        def forbidden(*args, **kwargs):
            raise AssertionError('read-aloud must not invoke the LLM')
        monkeypatch.setattr('src.server.voice_session.llm_response', forbidden)
        monkeypatch.setattr(state, 'avatar_streams', {701: avatar})
        monkeypatch.setattr(state, 'voice_sessions', {701: session})
        async def payload(): return {'sessionid': 701, 'type': 'echo', 'text': '固定朗讀', 'interrupt': True}
        try:
            session._gate_open = True
            response = await human(SimpleNamespace(json=payload))
            assert response.status == 200
            assert not session._gate_open, 'capture must pause before the first TTS PCM'
            text, envelope = messages[0]
            assert text == '固定朗讀'
            assert envelope['turn_id'] and envelope['fragment_sequence'] == 0
            assert session.accepts_media(envelope, 'test_read_aloud')
            assert session._llm_finished
            previous = envelope
            await human(SimpleNamespace(json=payload))
            assert not session.accepts_media(previous, 'test_read_aloud_cancelled')
            assert session.accepts_media(messages[-1][1], 'test_read_aloud_replacement')
        finally:
            await session.close()
    asyncio.run(run())


def test_disabled_voice_input_does_not_load_asr_or_open_capture(monkeypatch):
    from src.config.schema import Config
    from src.server.voice_session import VoiceTurnSession

    async def run():
        config = Config()
        config.vad.enabled = False
        session = VoiceTurnSession(702, config, SimpleNamespace(flush_talk=lambda: None))
        prepared = []
        monkeypatch.setattr(session, '_prepare_sync', lambda: prepared.append(True))
        try:
            await session.prepare()
            session.attach_event_sink(lambda _: None)
            session.handle_control('{"type":"capture","enabled":true}')
            assert prepared == [], 'read-aloud-only configuration must not load VAD or ASR'
            assert not session._gate_open
        finally:
            await session.close()
    asyncio.run(run())


@pytest.mark.parametrize('option,profile,height', [
    ('--realtime', 'config/config_jetson_realtime.yaml', 1280),
    ('--read-aloud', 'config/config_jetson_read_aloud.yaml', 1280),
])
def test_realtime_launcher_isolates_saved_preferences_without_extra_env_flags(tmp_path, option, profile, height):
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    fake_uv = tmp_path / 'uv'
    fake_uv.write_text('#!/bin/sh\nexit 0\n')
    fake_uv.chmod(0o755)
    fake_bash = tmp_path / 'bash'
    fake_bash.write_text(
        '#!' + sys.executable + '\n'
        'import json,sys\n'
        'from src.config.loader import load_config\n'
        'import src.config.overrides as overrides\n'
        'overrides.load_runtime_overrides=lambda: {"llm":{"provider":"llamacpp"}}\n'
        'c=load_config(sys.argv[2])\n'
        'print(json.dumps({"profile":sys.argv[2],"llm":c.llm.provider,"height":c.video.max_height,"vad":c.vad.enabled}))\n'
    )
    fake_bash.chmod(0o755)
    env = dict(os.environ, PATH=f'{tmp_path}:/usr/bin:/bin', PYTHONPATH=str(root))
    env.pop('NOVA_AVATAR_RUNTIME_OVERRIDES_ENABLED', None)
    result = subprocess.run(['/bin/bash', 'scripts/start-jetson.sh', option], cwd=root,
                            env=env, text=True, capture_output=True, check=True)
    loaded = json.loads(result.stdout.splitlines()[-1])
    assert loaded == {'profile': profile, 'llm': 'openai', 'height': height, 'vad': False}


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


def test_unet_engine_unsupported_conditioning_preserves_original_fallback():
    from threading import Lock
    from src.avatars.musetalk.inference_optimization import TensorRTUNet

    calls = []
    class Original(torch.nn.Module):
        dtype = torch.float32
        def forward(self, sample, timestep, **kwargs):
            calls.append((timestep, kwargs))
            return SimpleNamespace(sample=sample + timestep)
    engine = TensorRTUNet.__new__(TensorRTUNet)
    torch.nn.Module.__init__(engine)
    engine.original = Original()
    engine._lock, engine._failed, engine._stream = Lock(), False, None
    sample = torch.zeros(1, 8, 32, 32)
    features = torch.zeros(1, 50, 384)
    assert torch.all(engine(sample, 1, features).sample == 1)
    assert engine._failed
    assert torch.all(engine(sample, 2, features).sample == 2)
    assert [step for step, _ in calls] == [1, 2]
    assert calls[0][1]['encoder_hidden_states'] is features


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
    monkeypatch.setattr(module.time, 'sleep', delays.append)
    avatar = module.MuseTalkAvatar.__new__(module.MuseTalkAvatar)
    avatar.batch_size = 8
    avatar.max_tts_audio_wait_seconds = .2
    avatar.init_customindex = lambda: None
    avatar.tts = SimpleNamespace(render=lambda _: None, has_pending_work=lambda: False)
    avatar.audio_stream = SimpleNamespace(
        queue=SimpleNamespace(qsize=lambda: queued_audio, empty=lambda: queued_audio == 0),
        startup_batch_emitted=True, startup_batch_size=4,
        feat_queue=None, output_queue=None, run_step=quit_event.set,
    )
    for name in ('input_latent_list_cycle', 'res_frame_queue', 'vae', 'unet', 'pe', 'timesteps'):
        setattr(avatar, name, None)
    avatar.render(quit_event, video_track=SimpleNamespace(_queue=SimpleNamespace(qsize=lambda: 6)))
    assert delays == pytest.approx(expected_delay)


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
