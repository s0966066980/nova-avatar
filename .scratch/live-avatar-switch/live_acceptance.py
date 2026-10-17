# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Task-owned live acceptance on an isolated backend; no dialogue persistence."""
import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.run_role_soak import RolePeer
import aiohttp

BASE = 'https://localhost:8020'
OUTPUT = Path('.scratch/live-avatar-switch/live-acceptance.json')


async def run(base_url=BASE, output=OUTPUT):
    results = {}
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False),
            timeout=aiohttp.ClientTimeout(total=120)) as http:
        async def request(path, method='GET', body=None, *, expected=200):
            async with http.request(method, base_url+path, json=body) as r:
                data = await r.json()
                assert r.status == expected, (path, r.status)
                if expected == 200: assert data.get('code', 0) == 0, (path, data.get('code'))
                return data
        async def wait_role(peer, *, active='main', phase='ready', mode=None):
            return await peer.events.wait_for(lambda e: e.get('type') == 'role_state'
                and e.get('active_profile_id') == active and e.get('phase') == phase
                and (mode is None or e.get('mode') == mode))
        console = RolePeer(base_url, http, client_role='console')
        stage = RolePeer(base_url, http, client_role='stage')
        metrics = []
        for peer in (console, stage):
            def observe_metrics(raw, client_role=peer.client_role):
                event = json.loads(raw)
                if event.get('type') == 'turn_metrics':
                    metrics.append({'client_role': client_role, **event['metrics']})
            peer.channel.on('message', observe_metrics)
        asset_id = None
        try:
            await console.connect()
            await stage.connect()
            initial_tracks = [[r.track.id for r in p.pc.getReceivers()] for p in (stage, console)]
            await wait_role(console, mode='visitor')
            async with http.post(base_url+'/human', json={'sessionid':console.sessionid,
                    'type':'chat','text':'測試輸入來源','interrupt':False}) as r:
                assert (await r.json())['code'] == -1
            results['one_input_owner'] = True

            source = await request('/human', 'POST', {'sessionid':stage.sessionid,
                'type':'chat','text':'明天臺北市中正區會下雨嗎？','interrupt':False})
            await stage.events.wait_for(lambda e: e.get('type')=='role_state' and e.get('phase')=='announcement')
            interrupted_at = time.monotonic()
            stage.channel.send(json.dumps({'type':'interrupt'}))
            await stage.events.wait_for(lambda e:e.get('type')=='turn_cancelled' and e.get('turn_id')==source['turn_id'])
            await stage.events.wait_for(lambda e:e.get('type')=='state' and e.get('state')=='listening')
            results['announcement_interrupt_to_listening_event_seconds'] = time.monotonic() - interrupted_at
            assert (await request('/api/profiles'))['runtime']['active_profile_id']=='main'
            results['announcement_cancellation'] = True

            with tempfile.TemporaryDirectory(prefix='nova-role-clip-') as clip_dir:
                clip = Path(clip_dir) / 'probe.mp4'
                subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',
                    'color=blue:size=72x128:rate=25:duration=0.4','-f','lavfi','-i',
                    'sine=frequency=400:duration=0.4','-c:v','libx264','-c:a','aac',
                    '-shortest','-y',str(clip)],check=True,capture_output=True)
                form = aiohttp.FormData()
                with clip.open('rb') as handle:
                    form.add_field('file',handle,filename='owned-probe.mp4',content_type='video/mp4')
                    async with http.post(base_url+'/api/profiles/media',data=form) as r:
                        uploaded=await r.json();assert r.status==200
            asset_id=uploaded['asset']['id']
            assert uploaded['asset']['silent'] and uploaded['asset']['fps']==25
            results['silent_video_normalization'] = True
            library=(await request('/api/profiles'))['library']
            library['transitions']=[{'source':'main','target':'weather','kind':'video','asset_id':asset_id,
                'effect':'fade','duration':.6},{'source':'weather','target':'main','kind':'effect',
                'effect':'slide_right','duration':.2,'asset_id':''}]
            await request('/api/profiles','PUT',{'library':library,'expected_revision':library['revision']})
            await request('/api/profiles/apply','POST')
            await request('/api/profiles/media/'+asset_id,'DELETE',expected=409)
            results['referenced_media_delete_guard'] = True

            source=await request('/human','POST',{'sessionid':stage.sessionid,'type':'chat',
                'text':'明天臺北市中正區會下雨嗎？請簡短回答。','interrupt':False})
            handoff=await stage.events.wait_for(lambda e:e.get('type')=='role_handoff' and e.get('source_turn_id')==source['turn_id'])
            target=handoff['target_turn_id']
            await stage.events.wait_for(lambda e:e.get('type')=='speaking_start' and e.get('turn_id')==target)
            # Returning from either UI stops the input owner's current answer.
            returned_at = time.monotonic()
            await request('/api/profiles/return','POST')
            results['return_request_to_main_ready_seconds'] = time.monotonic() - returned_at
            committed=await stage.events.wait_for(lambda e:e.get('type')=='turn_committed' and e.get('turn_id')==target)
            assert committed['reason']=='interrupt'
            results['return_during_specialist_reply'] = True
            assert (await request('/api/profiles'))['runtime']['active_profile_id']=='main'
            results['directed_custom_video_and_return_effect'] = True
            assert [[r.track.id for r in p.pc.getReceivers()] for p in (stage, console)]==initial_tracks
            results['same_webrtc_tracks_both_clients'] = True

            await request('/api/profiles/mode','POST',{'mode':'console'})
            await wait_role(stage,mode='console')
            await wait_role(console,mode='console')
            assert stage.pc.connectionState=='connected' and console.pc.connectionState=='connected'
            results['mode_switch_preserves_both_connections'] = True

            async with http.post(base_url+'/human', json={'sessionid':stage.sessionid,
                    'type':'chat','text':'測試輸入來源','interrupt':False}) as r:
                assert (await r.json())['code'] == -1
            source=await request('/human','POST',{'sessionid':console.sessionid,'type':'chat',
                'text':'明天臺北市中正區會下雨嗎？請簡短回答。','interrupt':False})
            handoff=await console.events.wait_for(lambda e:e.get('type')=='role_handoff'
                and e.get('source_turn_id')==source['turn_id'])
            committed=await console.events.wait_for(lambda e:e.get('type')=='turn_committed'
                and e.get('turn_id')==handoff['target_turn_id'])
            assert committed['reason']=='completed'
            await console.events.wait_for(lambda e:e.get('type')=='turn_metrics'
                and e.get('turn_id')==handoff['target_turn_id'])
            await request('/api/profiles/return','POST')
            assert [[r.track.id for r in p.pc.getReceivers()] for p in (stage, console)]==initial_tracks
            assert console.events.stale_events==stage.events.stale_events==0
            results['console_handoff_with_both_clients_connected'] = True
            results['stale_fragment_events'] = 0

            # Explicitly reset the stage visitor's role memories via its reset API.
            await request('/clear_history','POST',{'sessionid':stage.sessionid})
            await stage.events.wait_for(lambda e:e.get('type')=='conversation_reset')
            results['visitor_memory_reset_event'] = True
            assert console.received['video'] and stage.received['video']
            results['both_clients_received_video'] = True
            results['transition_measurements'] = stage.transition_measurements
        finally:
            await console.close();await stage.close()
            await asyncio.sleep(1)
            if asset_id:
                library=(await request('/api/profiles'))['library']
                library['transitions']=[]
                await request('/api/profiles','PUT',{'library':library,'expected_revision':library['revision']})
                await request('/api/profiles/apply','POST')
                await request('/api/profiles/media/'+asset_id,'DELETE')
            results['turn_metrics'] = metrics
            results['browser_audiovisual_acceptance'] = 'not run; aiortc RTP receiver only'
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(results,indent=2)+'\n')
    return results

if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default=BASE)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    asyncio.run(run(args.base_url, args.output))
