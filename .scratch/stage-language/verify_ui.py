# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Exercise the deployed console and two real WebRTC stages using fixture audio."""
import asyncio
import base64
import json
import time
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / 'verification'
BASE = 'https://localhost:3000'
INIT = """
window.probeEvents=[];
const NativePC=window.RTCPeerConnection;
window.RTCPeerConnection=function(...args){
 const pc=new NativePC(...args); window.probePC=pc;
 const create=pc.createDataChannel.bind(pc);
 pc.createDataChannel=(...args)=>{const channel=create(...args); channel.addEventListener('message',e=>{try{window.probeEvents.push(JSON.parse(e.data))}catch(_){}});return channel;};
 return pc;
};
window.RTCPeerConnection.prototype=NativePC.prototype;
navigator.mediaDevices.getUserMedia=async()=>{
 const ctx=new AudioContext();await ctx.resume();window.probeAudio=ctx;
 const dest=ctx.createMediaStreamDestination(); window.probeDest=dest;
 const zero=ctx.createGain();zero.gain.value=0;const osc=ctx.createOscillator();osc.connect(zero).connect(dest);osc.start();
 return dest.stream;
};
window.playProbe=async(encoded)=>{
 const bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));
 const buffer=await window.probeAudio.decodeAudioData(bytes.buffer);
 const source=window.probeAudio.createBufferSource(); source.buffer=buffer; source.connect(window.probeDest);source.start();
 return buffer.duration;
};
"""


async def post(page, path, payload):
    response = await page.request.post(BASE + path, data=payload)
    body = await response.json()
    assert response.ok and body.get('code', 0) == 0, (path, response.status, body)
    return body


async def sessions(page):
    response = await page.request.get(BASE + '/api/conversations')
    return (await response.json())['data']


async def wait_event(page, kind, *, after=0, timeout=90000):
    await page.wait_for_function(
        '({kind,after})=>window.probeEvents.slice(after).some(e=>e.type===kind)',
        arg={'kind': kind, 'after': after}, timeout=timeout)
    return await page.evaluate('({kind,after})=>window.probeEvents.slice(after).find(e=>e.type===kind)',
                               {'kind': kind, 'after': after})


async def main():
    OUT.mkdir(exist_ok=True)
    evidence = {'started_at': time.time(), 'errors': []}
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path='/snap/chromium/current/usr/lib/chromium-browser/chrome',
            headless=True, args=['--no-sandbox', '--autoplay-policy=no-user-gesture-required'])
        contexts = []
        try:
            console_ctx = await browser.new_context(ignore_https_errors=True, viewport={'width':1440,'height':1000})
            contexts.append(console_ctx)
            console = await console_ctx.new_page()
            console.on('pageerror', lambda e: evidence['errors'].append(str(e)))
            await console.goto(BASE, wait_until='domcontentloaded')
            await console.locator('.conversation-panel').wait_for()
            await console.wait_for_function("document.querySelector('.conversation-panel button[type=submit]')?.disabled === true")
            await console.screenshot(path=str(OUT/'console-desktop.png'), full_page=True)
            await console.set_viewport_size({'width':375,'height':900})
            await console.screenshot(path=str(OUT/'console-mobile.png'), full_page=True)
            await console.set_viewport_size({'width':1440,'height':1000})
            pages, ids = [], []
            for locale in ('zh-TW','en-US'):
                context = await browser.new_context(ignore_https_errors=True, viewport={'width':720,'height':1000})
                contexts.append(context)
                await context.add_init_script(INIT)
                page = await context.new_page()
                page.on('pageerror', lambda e: evidence['errors'].append(str(e)))
                await page.goto(BASE+'/stage.html', wait_until='domcontentloaded')
                async with page.expect_response(lambda r:r.url.endswith('/offer'), timeout=90000) as pending:
                    await page.locator(f'#entryLanguages [data-locale="{locale}"]').click()
                offer = await pending.value
                body = await offer.json()
                assert offer.ok, body
                ids.append(body['sessionid']); pages.append(page)
                await page.wait_for_function("window.probeEvents.some(e=>e.type==='state'&&e.state==='listening')", timeout=90000)
                await page.wait_for_function("window.probePC.connectionState==='connected'", timeout=60000)
                assert await page.locator('html').get_attribute('lang') == locale
                await page.screenshot(path=str(OUT/f'stage-{locale}.png'))
            first, english = pages
            evidence['session_ids'] = ids
            current = await sessions(console)
            evidence['initial_sessions'] = current
            assert {s['locale'] for s in current['sessions']} >= {'zh-TW','en-US'}
            # The second stage uses a real uplink track containing generated English,
            # never a user's microphone. ASR -> LLM -> TTS -> WebRTC all execute.
            mp3 = ROOT/'.scratch/stage-language/edge-diagnosis/persistent-pool-en.mp3'
            count = await english.evaluate('window.probeEvents.length')
            await english.evaluate('encoded=>window.playProbe(encoded)', base64.b64encode(mp3.read_bytes()).decode())
            transcript = await wait_event(english, 'user_transcript', after=count)
            committed = await wait_event(english, 'turn_committed', after=count)
            evidence['english_voice_turn'] = {'transcript':transcript, 'commit':committed}
            assert transcript['text'].strip(), transcript
            assert committed['played_text'].strip(), committed
            assert any(c.isascii() and c.isalpha() for c in committed['played_text'])
            await english.wait_for_function("window.probeEvents.at(-1)?.state==='listening'")
            count = await english.evaluate('window.probeEvents.length')
            chinese_mp3 = ROOT/'.scratch/stage-language/edge-diagnosis/persistent-pool-zh.mp3'
            await english.evaluate('encoded=>window.playProbe(encoded)', base64.b64encode(chinese_mp3.read_bytes()).decode())
            chinese_input = await wait_event(english, 'user_transcript', after=count)
            english_answer = await wait_event(english, 'turn_committed', after=count)
            evidence['chinese_input_english_output'] = {'transcript':chinese_input, 'commit':english_answer}
            assert any('\u4e00' <= c <= '\u9fff' for c in chinese_input['text'])
            assert english_answer['played_text'] and not any('\u4e00' <= c <= '\u9fff' for c in english_answer['played_text'])
            # Seed a separate Chinese conversation, then switch while preserving it.
            count = await first.evaluate('window.probeEvents.length')
            await post(console, '/human', {'sessionid':ids[0],'type':'chat','text':'請記住本次測試的通關詞 NOVA42，回答收到即可。','interrupt':False})
            await wait_event(first, 'turn_committed', after=count)
            await post(console, f'/api/conversations/{ids[0]}', {'locale':'en-US'})
            await first.wait_for_function("document.documentElement.lang==='en-US'")
            memory = next(s for s in (await sessions(console))['sessions'] if s['sessionid']==ids[0])
            evidence['after_switch'] = memory
            assert memory['memory']['retained_messages'] >= 2, memory
            count = await first.evaluate('window.probeEvents.length')
            await post(console, '/human', {'sessionid':ids[0],'type':'chat','text':'What code did I ask you to remember?','interrupt':False})
            answer = await wait_event(first, 'turn_committed', after=count)
            evidence['cross_language_memory'] = answer
            assert 'NOVA42' in answer['played_text'].upper(), answer
            # Apply a limit through the controller UI, including numeric serialization.
            await console.locator('.conversation-heading select').select_option(str(ids[0]))
            await console.locator('.conversation-panel summary').click()
            await console.locator('.conversation-panel input[type=number]').fill('3')
            await console.locator('.conversation-panel button[type=submit]').click()
            await console.locator('.conversation-feedback').filter(has_text='已套用').wait_for()
            await console.locator('.conversation-panel summary').click()
            await console.locator('.conversation-panel').evaluate('el=>el.scrollTop=0')
            await console.screenshot(path=str(OUT/'console-memory.png'), full_page=True)
            evidence['controller_after_apply'] = await sessions(console)
            count = await first.evaluate('window.probeEvents.length')
            started = await post(console, '/human', {'sessionid':ids[0],'type':'chat','text':'Describe a visit to a museum in three full sentences.','interrupt':True})
            speaking = await wait_event(first, 'speaking_start', after=count)
            await first.locator('#stageLocale').select_option('zh-TW')
            await first.wait_for_function("document.documentElement.lang==='zh-TW' && !document.querySelector('#stageLocale').disabled", timeout=20000)
            after = await first.evaluate('window.probeEvents.length')
            await first.wait_for_timeout(500)
            late = await first.evaluate('after=>window.probeEvents.slice(after)', after)
            assert not [e for e in late if e.get('type')=='assistant_fragment' and e.get('turn_id')==speaking['turn_id']], late
            evidence['mid_reply_switch'] = {'cancelled_turn':speaking['turn_id'], 'sessions':(await sessions(console))['sessions']}
            assert next(s for s in evidence['mid_reply_switch']['sessions'] if s['sessionid']==ids[1])['locale']=='en-US'
            inbound = await english.evaluate("async()=>[...(await window.probePC.getStats()).values()].filter(s=>s.type==='inbound-rtp'&&s.kind==='audio').map(s=>({bytes:s.bytesReceived,energy:s.totalAudioEnergy}))")
            evidence['english_received_audio'] = inbound
            assert inbound and inbound[0]['bytes']>0 and inbound[0]['energy']>0, inbound
            async with english.expect_response(lambda r:r.url.endswith('/offer') and r.status==200, timeout=60000) as pending:
                await english.evaluate('window.probePC.close()')
            replacement = await (await pending.value).json()
            assert replacement['sessionid'] != ids[1]
            await english.wait_for_function("window.probePC.connectionState==='connected'", timeout=30000)
            assert await english.locator('html').get_attribute('lang') == 'en-US'
            evidence['reconnect'] = {'new_sessionid':replacement['sessionid'], 'message':await english.locator('#said').inner_text()}
            assert 'memory was cleared' in evidence['reconnect']['message']
            evidence['errors'] = list(dict.fromkeys(evidence['errors']))
            assert not evidence['errors'], evidence['errors']
            evidence['passed'] = True
        except Exception as exc:
            evidence['passed'] = False; evidence['failure'] = str(exc)
            for index, context in enumerate(contexts):
                for number, page in enumerate(context.pages):
                    try:
                        await page.screenshot(path=str(OUT/f'failure-{index}-{number}.png'))
                        evidence[f'events_{index}_{number}'] = await page.evaluate('window.probeEvents || []')
                    except Exception:
                        pass
            raise
        finally:
            (OUT/'browser-results.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
            for context in contexts:
                await context.close()
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
