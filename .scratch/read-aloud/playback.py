# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Exercise real /offer and /human echo over local HTTP and H264 WebRTC."""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
import numpy as np
from aiohttp import ClientSession, web
from aiortc import RTCPeerConnection, RTCConfiguration, RTCSessionDescription
from src.avatars.factory import prepare_avatar_model
from src.config.loader import load_config
from src.scene.service import scene_service
from src.server.server import create_app
from src.server.state import state
import src.server.routes.webrtc as rtc_route
from src.utils.webrtc import HumanPlayer


async def run(args):
    config = load_config(args.config)
    config.customopt = []
    # The harness never starts or calls an LLM, including on the baseline.
    config.llm.provider = 'openai'
    config.vad.enabled = False
    state.config = config
    state.model, state.avatar = prepare_avatar_model(config)
    state.model_ready = state.server_ready = state.reply_prewarm_ready = True
    source = []
    sent = []
    video = {}
    decoded = {'audio': [], 'video': []}
    completed = asyncio.Event()
    started = None
    first_pcm = None
    drainers = []
    error_events = []
    class Background:
        def frame(self, width, height): return np.full((height, width, 3), 80, np.uint8)
        def close(self): pass
    scene_service._source = Background()
    class Player(HumanPlayer):
        def __init__(self, avatar, **kwargs):
            nonlocal first_pcm
            original_put = avatar.put_audio_frame
            def put(chunk, event):
                nonlocal first_pcm
                accepted = original_put(chunk, event)
                if accepted:
                    first_pcm = first_pcm or time.monotonic()
                    source.append(len(chunk))
                return accepted
            avatar.put_audio_frame = put
            self.avatar = avatar
            super().__init__(avatar, **kwargs)
        def notify_audio_frame(self, event, active):
            super().notify_audio_frame(event, active)
            if event is not None:
                sent.append((time.monotonic(), event))
                if event.get('status') == 'end' or event.get('fragment_end'):
                    completed.set()
        def notify_media_timing(self, kind, seconds, event=None):
            super().notify_media_timing(kind, seconds, event)
            if kind == 'video' and event and event.get('turn_id'):
                video.setdefault(event.get('media_sequence'), time.monotonic())
    rtc_route.HumanPlayer = Player
    pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    connected = asyncio.Event()
    channel = pc.createDataChannel('voice-events')
    @channel.on('message')
    def message(raw):
        event = json.loads(raw)
        if event.get('type') in ('turn_cancelled',) or event.get('state') in ('error', 'degraded'):
            error_events.append(event.get('reason') or event.get('error') or event.get('state'))
    @pc.on('connectionstatechange')
    def changed():
        if pc.connectionState == 'connected': connected.set()
    async def drain(track):
        try:
            while True:
                frame = await track.recv()
                if started is not None:
                    decoded[track.kind].append(time.monotonic())
        except Exception:
            pass
    @pc.on('track')
    def track(track): drainers.append(asyncio.create_task(drain(track)))
    pc.addTransceiver('audio', direction='recvonly')
    pc.addTransceiver('video', direction='recvonly')
    runner = web.AppRunner(create_app())
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    report = {}
    try:
        async with ClientSession() as client:
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            async with client.post(f'http://127.0.0.1:{port}/offer', json={
                'sdp': pc.localDescription.sdp, 'type': pc.localDescription.type,
            }) as response:
                answer = await response.json()
                assert response.status == 200, answer
            await pc.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'], type=answer['type']))
            await asyncio.wait_for(connected.wait(), 10)
            while channel.readyState != 'open': await asyncio.sleep(.01)
            await asyncio.sleep(.5)
            started = time.monotonic()
            async with client.post(f'http://127.0.0.1:{port}/human', json={
                'sessionid': answer['sessionid'], 'type': 'echo', 'interrupt': True,
                'text': '今天的測試會先確認聲音是否連續。接著比較嘴型推理造成的等待。最後記錄整段語音的播放時間。',
            }) as response:
                ack = await response.json()
                assert response.status == 200 and ack['code'] == 0, ack
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                avatar = state.avatar_streams[answer['sessionid']]
                if source and len(sent) * 320 >= sum(source) and not avatar.tts.has_pending_work():
                    break
                await asyncio.sleep(.02)
            await asyncio.sleep(.2)
            seconds = sum(source) / 16000
            times = [item[0] for item in sent]
            audio_keys = {event.get('media_sequence'): when for when, event in sent if event.get('turn_id')}
            offsets = [abs(audio_keys[key] - when) * 1000 for key, when in video.items() if key in audio_keys]
            report = {
                'config': args.config, 'route': '/human type=echo', 'llm_called': False,
                'vad_enabled': config.vad.enabled,
                'decoder': type(state.model[0]).__name__, 'unet': type(state.model[1].model).__name__,
                'max_height': config.video.max_height, 'source_seconds': seconds,
                'sent_seconds': len(sent) * .02,
                'playback_wall_seconds': times[-1] - times[0] + .02,
                'text_to_audio_seconds': times[0] - started,
                'pcm_to_audio_seconds': times[0] - first_pcm,
                'max_audio_gap_ms': max(np.diff(times)) * 1000,
                'mouth_coverage': len(offsets) / max(1, len(sent) / 2),
                'av_p95_ms': float(np.percentile(offsets, 95)) if offsets else None,
                'decoded_audio_frames': len(decoded['audio']), 'decoded_video_frames': len(decoded['video']),
                'errors': error_events,
                'decoder_failed': bool(getattr(state.model[0], '_failed', False)),
                'unet_failed': bool(getattr(state.model[1].model, '_failed', False)),
            }
            report['pass'] = bool(abs(report['sent_seconds'] - seconds) < .001
                and report['max_audio_gap_ms'] < 60 and report['mouth_coverage'] >= .95
                and report['av_p95_ms'] is not None and report['av_p95_ms'] <= 80
                and report['playback_wall_seconds'] <= seconds + .1
                and not report['errors'] and not report['decoder_failed'] and not report['unet_failed'])
            Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
            print(json.dumps(report, ensure_ascii=False), flush=True)
    finally:
        await pc.close()
        await runner.cleanup()
        for task in drainers: task.cancel()
        await asyncio.gather(*drainers, return_exceptions=True)
    assert report.get('pass'), 'Read-aloud realtime gate failed'

parser = argparse.ArgumentParser()
parser.add_argument('--config', default='config/config_jetson_realtime.yaml')
parser.add_argument('--output', required=True)
asyncio.run(run(parser.parse_args()))
