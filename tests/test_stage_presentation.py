# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

import asyncio
from fractions import Fraction
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock

import numpy as np
from av import AudioFrame, VideoFrame

from src.server.presentation import SessionPresentation


class SourceTrack:
    def __init__(self, kind):
        self.kind = kind
        self.frames = asyncio.Queue()
        self.last_eventpoint = None
        self.read_count = 0

    async def recv(self):
        frame, self.last_eventpoint = await self.frames.get()
        self.read_count += 1
        return frame

    def feed(self, value, generation=0, pts=None):
        if self.kind == 'audio':
            frame = AudioFrame.from_ndarray(np.full((1, 320), value, dtype=np.int16), format='s16', layout='mono')
            frame.sample_rate = 16000
        else:
            frame = VideoFrame.from_ndarray(np.full((16, 16, 3), value, dtype=np.uint8), format='rgb24')
        frame.pts = pts
        frame.time_base = Fraction(1, 16000 if self.kind == 'audio' else 90000)
        self.frames.put_nowait((frame, dict(generation=generation, avatar_epoch=0)))


class PresentationTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.roles = SimpleNamespace(input_mode_managed=True, mode='console')
        self.hub = SessionPresentation(SimpleNamespace(roles=self.roles))
        self.voices, self.players, self.outputs, self.events = {}, {}, {}, {}
        for sid, role in enumerate(['console', 'stage'], 1):
            self.events[role] = []
            voice = SimpleNamespace(sessionid=sid, _presenter=role, _closed=False, _generation=0,
                avatar=SimpleNamespace(_asset_epoch=0), _acknowledge_board=Mock(),
                _send_event=self.events[role].append)
            player = SimpleNamespace(audio=SourceTrack('audio'), video=SourceTrack('video'))
            self.voices[role], self.players[role] = voice, player
            self.outputs[role] = self.hub.register(voice, player)
        for events in self.events.values():
            events.clear()

    async def asyncTearDown(self):
        for sid in list(self.hub.sources):
            await self.hub.unregister(sid)
        self.assertFalse(self.hub.tracks)
        self.assertFalse(self.hub.last_media)

    async def both_frames(self, kind):
        index = 0 if kind == 'audio' else 1
        return await asyncio.wait_for(asyncio.gather(
            *(tracks[index].recv() for tracks in self.outputs.values())), .5)

    async def test_same_active_audio_and_lip_frames_on_both_pages_with_monotonic_switch(self):
        for mode, role, value in [('console', 'console', 40), ('visitor', 'stage', 180)]:
            self.roles.mode = mode
            self.hub.refresh()
            self.players[role].audio.feed(value)
            self.players[role].video.feed(value)
            audio = await self.both_frames('audio')
            video = await self.both_frames('video')
            for frame in audio:
                self.assertEqual(np.unique(frame.to_ndarray()).tolist(), [value])
            for frame in video:
                self.assertLess(abs(float(frame.to_ndarray(format='rgb24').mean()) - value), 3)
            self.assertIsNot(audio[0], audio[1])
            self.assertIsNot(video[0], video[1])
            if mode == 'console':
                previous_audio, previous_video = audio[0].pts, video[0].pts
            else:
                self.assertGreater(audio[0].pts, previous_audio)
                self.assertGreater(video[0].pts, previous_video)
        self.assertEqual(self.players['console'].audio.read_count, 1)
        self.assertEqual(self.players['stage'].audio.read_count, 1)

    async def test_cancelled_or_late_generation_cannot_reach_either_page(self):
        self.hub.start()
        self.players['console'].audio.feed(100)
        await asyncio.sleep(.01)
        self.voices['console']._generation += 1
        self.hub.publish(self.voices['console'], dict(type='turn_cancelled', turn_id='old'))
        self.players['console'].audio.feed(200, generation=0)
        self.players['console'].audio.feed(300, generation=1)
        for frame in await self.both_frames('audio'):
            self.assertEqual(np.unique(frame.to_ndarray()).tolist(), [300])

    async def test_video_keeps_source_timestamp_skips_instead_of_falling_behind_audio(self):
        self.players['console'].video.feed(40, pts=0)
        first = await self.both_frames('video')
        self.players['console'].video.feed(50, pts=10800)
        second = await self.both_frames('video')
        self.assertEqual(second[0].pts - first[0].pts, 10800)
        self.assertEqual(second[0].pts, second[1].pts)

    async def test_slow_observer_has_bounded_buffer_and_does_not_delay_owner_audio(self):
        owner = self.outputs['console'][0]
        observer = self.outputs['stage'][0]
        for index in range(8):
            self.players['console'].audio.feed(index)
            frame = await asyncio.wait_for(owner.recv(), .5)
            self.assertEqual(int(frame.to_ndarray()[0, 0]), index)
        self.assertEqual(observer.queue.qsize(), observer.queue.maxsize)
        self.assertEqual(int((await observer.recv()).to_ndarray()[0, 0]), 6)
        self.assertEqual(int((await observer.recv()).to_ndarray()[0, 0]), 7)

    async def test_snapshot_replays_current_played_scene_and_modes_keep_separate_memories(self):
        console, stage = self.voices['console'], self.voices['stage']
        self.hub.publish(console, dict(type='user_transcript', turn_id='c', text='控制台問題'))
        self.hub.publish(console, dict(type='assistant_response_delta', turn_id='c', text_delta='尚未播放'))
        self.hub.publish(console, dict(type='assistant_fragment', turn_id='c', text='控制台已播回答'))
        self.hub.publish(console, dict(type='board_item', turn_id='c', board_id='c', index=0, title='測試項目'))
        self.events['stage'].clear()
        self.hub.replay(stage)
        self.assertEqual([e['type'] for e in self.events['stage']],
            ['presentation_reset', 'user_transcript', 'assistant_fragment', 'board_item'])
        self.assertTrue(all(e['mirrored'] for e in self.events['stage'][1:]))
        self.roles.mode = 'visitor'
        self.hub.refresh()
        self.hub.publish(stage, dict(type='user_transcript', turn_id='s', text='訪客問題'))
        self.hub.publish(stage, dict(type='assistant_fragment', turn_id='s', text='訪客已播回答'))
        self.assertEqual(self.events['console'][-1]['text'], '訪客已播回答')
        self.hub.publish(console, dict(type='state', state='paused'))
        self.assertEqual(self.events['console'][-1]['text'], '訪客已播回答')
        self.roles.mode = 'console'
        self.hub.refresh()
        reset = max(i for i, event in enumerate(self.events['stage']) if event['type'] == 'presentation_reset')
        self.assertEqual([e['text'] for e in self.events['stage'][reset + 1:] if 'text' in e],
                         ['控制台問題', '控制台已播回答'])

    async def test_mirrored_board_receipt_targets_source_session(self):
        receipt = dict(type='board_displayed', presenter='stage', turn_id='c', board_id='c', item_index=0)
        self.assertTrue(self.hub.acknowledge_board(self.voices['stage'], receipt))
        self.voices['console']._acknowledge_board.assert_called_once_with(receipt, presenter='stage')
        self.voices['stage']._acknowledge_board.assert_not_called()

    async def test_long_turn_snapshot_keeps_question_board_and_all_played_fragments(self):
        source = self.voices['console']
        self.hub.publish(source, dict(type='user_transcript', turn_id='c', text='目前問題'))
        self.hub.publish(source, dict(type='board_begin', turn_id='c', title='目前看板'))
        self.hub.publish(source, dict(type='board_item', turn_id='c', index=0, title='可見項目'))
        for _ in range(200):
            self.hub.publish(source, dict(type='assistant_fragment', turn_id='c', text='已播'))
            self.hub.publish(source, dict(type='state', turn_id='c', state='avatar_speaking'))
        self.events['stage'].clear()
        self.hub.replay(self.voices['stage'])
        events = self.events['stage']
        self.assertEqual(next(e['text'] for e in events if e['type'] == 'user_transcript'), '目前問題')
        self.assertEqual(''.join(e['text'] for e in events if e['type'] == 'assistant_fragment'), '已播' * 200)
        self.assertEqual(sum(e['type'] == 'assistant_fragment' for e in events), 200)
        self.assertEqual(next(e['title'] for e in events if e['type'] == 'board_item'), '可見項目')

    async def test_disconnect_keeps_other_peer_and_discards_old_scene(self):
        self.hub.publish(self.voices['console'], dict(type='user_transcript', turn_id='c', text='舊問題'))
        await self.hub.unregister(self.voices['console'].sessionid)
        self.assertEqual(self.events['stage'][-1]['type'], 'presentation_reset')
        self.assertTrue(all(track.readyState == 'live' for track in self.outputs['stage']))
        self.players['stage'].audio.feed(500)
        frame = await asyncio.wait_for(self.outputs['stage'][0].recv(), .5)
        self.assertEqual(int(frame.to_ndarray()[0, 0]), 500)
