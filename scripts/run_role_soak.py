#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Exercise real role handoffs over WebRTC; persist only scalar measurements."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path
import sys
import time

import aiohttp
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.run_voice_soak import SoakPeer, synthesize_fixture


class RolePeer(SoakPeer):
    def __init__(self, *args, **kwargs):
        self.received = Counter()
        self.video_sizes = set()
        self.timeline = {}
        self.weather_status = Counter()
        self.weather_queries = {}
        self.transitions = []
        self.transition_measurements = []
        self.transition_completed = {}
        self._transition_started = None
        super().__init__(*args, **kwargs)
        self.channel.on('message', self.observe)

    def observe(self, raw):
        event = json.loads(raw)
        now = time.monotonic()
        kind, tid = event.get('type'), event.get('turn_id')
        if tid:
            self.timeline.setdefault(tid, {}).setdefault(kind, now)
        if kind == 'role_state':
            if event['phase'] == 'transition' and self._transition_started is None:
                self._transition_started = now
            elif event['phase'] == 'ready' and self._transition_started is not None:
                self.transitions.append(now - self._transition_started)
                self._transition_started = None
        if kind == 'weather_result':
            self.weather_status[event['result']['status']] += 1
            self.weather_queries[tid] = {key: event['result'].get(key)
                for key in ('status', 'cached', 'query_seconds')}
        if kind == 'role_transition_started':
            self.transition_measurements.append({k:event[k] for k in ('preparation_seconds','duration_seconds')})
        if kind == 'role_transition_completed':
            self.transition_completed[event['transition_id']] = now
            if self.transition_measurements:
                self.transition_measurements[-1]['sender_elapsed_seconds'] = event['elapsed_seconds']
        if kind == 'role_error':
            self.received['role_errors'] += 1

    async def _drain(self, track):
        try:
            while True:
                frame = await track.recv()
                self.received[track.kind] += 1
                if track.kind == 'video':
                    self.video_sizes.add((frame.width, frame.height))
                elif np.any(frame.to_ndarray()):
                    self.received['non_silent_audio'] += 1
        except Exception:
            return


def percentile(values, p):
    return float(np.percentile(values, p)) if values else None


async def run(args):
    samples = None if args.typed else await synthesize_fixture(args.question, args.voice)
    summaries = []
    def checkpoint():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({'runs': summaries,
            'browser_audiovisual_acceptance': 'not run; aiortc RTP receiver only'}, indent=2) + '\n')
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=120)) as http:
        async def post(path, body=None):
            async with http.post(args.base_url + path, json=body) as response:
                result = await response.json()
                if response.status != 200 or result.get('code') == -1:
                    raise RuntimeError(f'{path}: HTTP {response.status}')
                return result
        async with http.get(args.base_url + '/api/profiles') as response:
            runtime = (await response.json())['runtime']
        if not runtime['enabled']:
            raise RuntimeError('Enable a validated role pair before running the soak')
        for presenter in args.presenters:
            await post('/api/profiles/mode', {'mode': 'console' if presenter == 'console' else 'visitor'})
            peer = RolePeer(args.base_url, http, client_role=presenter)
            latencies, cached_latencies, turns = [], [], []
            started = time.monotonic()
            summary = {'presenter': presenter, 'completed_handoffs': 0,
                'input': 'typed' if args.typed else 'synthetic_microphone'}
            summaries.append(summary)
            try:
                await peer.connect()
                await post('/api/profiles/return')
                peer.transitions.clear()
                for index in range(args.turns):
                    accepted_at = time.monotonic()
                    if samples is None:
                        accepted = await post('/human', {'sessionid': peer.sessionid,
                            'type': 'chat', 'text': args.question, 'interrupt': False})
                        source_turn = accepted['turn_id']
                    else:
                        peer.audio.push(samples)
                        event = await peer.events.wait_for(lambda e: e.get('type') == 'user_transcript')
                        source_turn = event['turn_id']
                    handoff = await peer.events.wait_for(lambda e: e.get('type') == 'role_handoff'
                        and e.get('source_turn_id') == source_turn)
                    target_turn = handoff['target_turn_id']
                    result = await peer.events.wait_for(lambda e: e.get('type') == 'turn_committed'
                        and e.get('turn_id') == target_turn)
                    if result['reason'] != 'completed':
                        raise RuntimeError('Specialist reply did not complete')
                    source_metrics = (await peer.events.wait_for(lambda e: e.get('type') == 'turn_metrics'
                        and e.get('turn_id') == source_turn))['metrics']
                    target_metrics = (await peer.events.wait_for(lambda e: e.get('type') == 'turn_metrics'
                        and e.get('turn_id') == target_turn))['metrics']
                    source, target = peer.timeline[source_turn], peer.timeline[target_turn]
                    first_audio = target.get('speaking_start')
                    # Target turn is accepted only after the transition's sender fence.
                    handoff_at = peer.transition_completed.get(handoff['handoff_id'], target.get('state'))
                    latency = first_audio - handoff_at if first_audio and handoff_at else None
                    if latency is not None:
                        latencies.append(latency)
                        if peer.weather_queries.get(target_turn, {}).get('cached'):
                            cached_latencies.append(latency)
                    turns.append({'source_first_audio_seconds': source_metrics['first_audio_seconds'],
                        'input_start_to_source_audio_seconds': source.get('speaking_start', accepted_at) - accepted_at,
                        'specialist_first_audio_seconds': latency,
                        'source_to_target_audio_seconds': first_audio - source['speaking_end'] if first_audio else None,
                        'source_metrics': source_metrics, 'specialist_metrics': target_metrics,
                        'weather_query': peer.weather_queries.get(target_turn)})
                    await post('/api/profiles/return')
                    summary.update(completed_handoffs=len(turns),
                        specialist_first_audio_p95_seconds=percentile(latencies, 95),
                        cached_specialist_first_audio_p95_seconds=percentile(cached_latencies, 95),
                        received_frames=dict(peer.received), video_sizes=sorted(peer.video_sizes),
                        weather_status=dict(peer.weather_status), stale_events=peer.events.stale_events,
                        transition_seconds=peer.transitions, turns=turns)
                    summary['transition_measurements'] = peer.transition_measurements
                    checkpoint()
                    print(f'{presenter}: {index + 1}/{args.turns}', flush=True)
                summary['status'] = 'completed'
            except Exception as exc:
                summary.update(status='failed', failure_type=type(exc).__name__)
                raise
            finally:
                summary['elapsed_seconds'] = time.monotonic() - started
                checkpoint()
                await peer.close()
                # Allow the backend's peer-closed callback to release its slot.
                await asyncio.sleep(.5)
    return {'runs': summaries, 'browser_audiovisual_acceptance': 'not run; aiortc RTP receiver only'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='https://localhost:8010')
    parser.add_argument('--presenters', nargs='+', choices=['stage', 'console'], default=['stage', 'console'])
    parser.add_argument('--turns', type=int, default=50)
    parser.add_argument('--question', default='明天臺北市中正區會下雨嗎？請簡短回答。')
    parser.add_argument('--voice', default='zh-TW-HsiaoChenNeural')
    parser.add_argument('--typed', action='store_true', help='Skip STT; still receive real audio/video')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.turns < 1:
        parser.error('--turns must be positive')
    result = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
