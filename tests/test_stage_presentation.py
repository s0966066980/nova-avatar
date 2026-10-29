# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

import asyncio
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock

from src.server.presentation import SessionPresentation


class PresentationTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hub = SessionPresentation(None)
        self.voices, self.players, self.outputs, self.events = {}, {}, {}, {}
        for sid, role in enumerate(['console', 'stage'], 1):
            self.events[role] = []
            voice = SimpleNamespace(sessionid=sid, _presenter=role,
                _send_event=self.events[role].append)
            player = SimpleNamespace(audio=asyncio.Queue(), video=asyncio.Queue())
            self.voices[role], self.players[role] = voice, player
            self.outputs[role] = self.hub.register(voice, player)

    async def asyncTearDown(self):
        for sid in list(self.hub.sources):
            await self.hub.unregister(sid)
        self.assertFalse(self.hub.sources)

    async def test_each_peer_sends_its_own_player_tracks_without_a_shared_source(self):
        for role in ['console', 'stage']:
            self.assertIs(self.outputs[role][0], self.players[role].audio)
            self.assertIs(self.outputs[role][1], self.players[role].video)
        self.players['console'].audio.put_nowait('console audio')
        self.players['stage'].audio.put_nowait('stage audio')
        self.assertEqual(await self.outputs['console'][0].get(), 'console audio')
        self.assertEqual(await self.outputs['stage'][0].get(), 'stage audio')

    async def test_concurrent_answers_and_cancellations_never_cross_pages(self):
        for role, voice in self.voices.items():
            self.hub.publish(voice, dict(type='user_transcript', turn_id=role, text=role))
            self.hub.publish(voice, dict(type='assistant_fragment', turn_id=role, text=role))
        self.hub.publish(self.voices['console'], dict(type='turn_cancelled', turn_id='console'))
        self.assertEqual(len(self.events['stage']), 2)
        self.assertTrue(all(e.get('turn_id') == 'stage' for e in self.events['stage']))
        self.assertTrue(all(e.get('turn_id') == 'console' for e in self.events['console']))

    async def test_replay_contains_only_the_receiving_conversations_played_content(self):
        for role, voice in self.voices.items():
            self.hub.publish(voice, dict(type='user_transcript', turn_id=role, text=role))
            self.hub.publish(voice, dict(type='assistant_response_delta', turn_id=role, text_delta='preview'))
            self.hub.publish(voice, dict(type='assistant_fragment', turn_id=role, text=role))
        for role, voice in self.voices.items():
            self.events[role].clear()
            self.hub.replay(voice)
            replay = self.events[role]
            self.assertEqual([e['type'] for e in replay],
                ['presentation_reset', 'user_transcript', 'assistant_fragment'])
            self.assertTrue(all(e.get('text') == role for e in replay[1:]))

    async def test_board_receipts_are_not_redirected_to_another_session(self):
        for voice in self.voices.values():
            self.assertFalse(self.hub.acknowledge_board(voice, dict(type='board_displayed')))

    async def test_disconnect_leaves_the_other_peers_media_and_events_usable(self):
        await self.hub.unregister(self.voices['console'].sessionid)
        stage = self.voices['stage']
        self.assertIs(stage._presentation, self.hub)
        self.hub.publish(stage, dict(type='assistant_fragment', text='still playing'))
        self.assertEqual(self.events['stage'][-1]['text'], 'still playing')
        self.assertIs(self.outputs['stage'][0], self.players['stage'].audio)

    async def test_full_reset_removes_only_that_conversations_replay(self):
        for role, voice in self.voices.items():
            self.hub.publish(voice, dict(type='assistant_fragment', turn_id=role, text=role))
        self.hub.publish(self.voices['stage'], dict(type='conversation_reset', turn_id=None))
        for events in self.events.values():
            events.clear()
        for voice in self.voices.values():
            self.hub.replay(voice)
        self.assertEqual(self.events['console'][-1]['text'], 'console')
        self.assertFalse(any('text' in e for e in self.events['stage']))
