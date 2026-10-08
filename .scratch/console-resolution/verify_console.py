# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Real console settings and synthesized playback; never acquire a microphone."""
import asyncio
import argparse
import base64
import json
from pathlib import Path
import wave

import numpy as np
from playwright.async_api import async_playwright

OUT = Path('.scratch/console-resolution')
parser = argparse.ArgumentParser()
parser.add_argument('--playback-only', action='store_true')
parser.add_argument('--label', default='console-playback')
parser.add_argument('--height', type=int, default=540)
parser.add_argument('--headless', action='store_true')
args = parser.parse_args()
TEXT = '今天的測試會先確認聲音是否連續。接著比較嘴型推理造成的等待。最後記錄整段語音的播放時間。'
INIT = r"""
window.probe={pcs:[],events:[],frames:[],chunks:[],measuring:false,recording:false};
const Original=window.RTCPeerConnection;
window.RTCPeerConnection=class extends Original {
 constructor(...args){super(...args);probe.pcs.push(this);}
 createDataChannel(...args){const channel=super.createDataChannel(...args);
  channel.addEventListener('message',e=>{try{probe.events.push({time:performance.now(),...JSON.parse(e.data)});}catch{}});
  return channel;
 }
};
navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('Text-only diagnostic','NotAllowedError');};
"""
STATS = """async()=>{const out={};for(const r of (await probe.pcs.at(-1).getStats()).values())
if(r.type==='inbound-rtp')out[r.kind]=r;return out;}"""
CAPTURE = r"""async()=>{
 const video=document.getElementById('video');
 probe.context=new AudioContext({sampleRate:48000});
 const code=`class Capture extends AudioWorkletProcessor {process(inputs){
  if(inputs[0]?.[0]){const pcm=new Float32Array(inputs[0][0]);this.port.postMessage(pcm,[pcm.buffer]);}
  return true;}}registerProcessor('capture',Capture);`;
 const url=URL.createObjectURL(new Blob([code],{type:'text/javascript'}));
 await probe.context.audioWorklet.addModule(url);URL.revokeObjectURL(url);
 probe.source=probe.context.createMediaStreamSource(new MediaStream(video.srcObject.getAudioTracks()));
 probe.capture=new AudioWorkletNode(probe.context,'capture');
 probe.capture.port.onmessage=e=>{if(probe.recording)probe.chunks.push(e.data);};
 probe.source.connect(probe.capture);probe.capture.connect(probe.context.destination);await probe.context.resume();
 // Read compositor metadata only. Synchronous canvas/GPU readback can itself
 // delay callbacks while the local inference process is using the same GPU.
 function tick(now,meta){
  if(probe.measuring)probe.frames.push({now,presentedFrames:meta.presentedFrames,
    presentationTime:meta.presentationTime,expectedDisplayTime:meta.expectedDisplayTime});
  video.requestVideoFrameCallback(tick);
 }video.requestVideoFrameCallback(tick);
}"""
PCM = r"""()=>{
 const pcm=new Int16Array(probe.chunks.reduce((s,c)=>s+c.length,0));let offset=0;
 for(const chunk of probe.chunks)for(const sample of chunk)pcm[offset++]=Math.round(Math.max(-1,Math.min(1,sample))*32767);
 const bytes=new Uint8Array(pcm.buffer);let str='';
 for(let i=0;i<bytes.length;i+=32768)str+=String.fromCharCode(...bytes.subarray(i,i+32768));return btoa(str);
}"""


async def settings(page, height, reconnect=False):
    await page.locator('#btnViewSettings').click()
    await page.locator('#railTab-avatar').click()
    select = page.get_by_label('數字人輸出解析度', exact=True)
    previous = await select.input_value()
    await select.select_option(str(height))
    row = page.locator('#avatar-output-dimensions')
    expected = {450: '252 × 450', 540: '304 × 540', 960: '540 × 960'}[height]
    assert expected in await row.inner_text()
    if previous != str(height):
        await page.get_by_role('button', name='儲存解析度', exact=True).click()
    await page.wait_for_function("document.querySelector('#avatar-output-height')?.disabled===false")
    saved = await page.evaluate("async()=>{const r=await fetch('/api/settings');return (await r.json()).data.video;}")
    assert saved['max_height'] == height
    assert saved['output_width'] == int(expected.split(' × ')[0])
    if reconnect:
        await page.get_by_text('解析度已儲存，請中斷並重新啟動連線以套用。', exact=True).wait_for()
    await page.screenshot(path=str(OUT / 'console-resolution-settings.png'))
    await page.locator('#btnViewConsole').click()
    print(f'Settings verified: height {height}', flush=True)


async def connect(page, width, height):
    await page.locator('.stage-footer-actions > button').first.click(timeout=30000)
    await page.wait_for_function("([w,h])=>{const v=document.getElementById('video');return v?.videoWidth===w&&v?.videoHeight===h}", arg=[width, height], timeout=60000)
    print(f'Connected video: {width}x{height}', flush=True)


async def disconnect(page):
    await page.locator('.stage-footer-actions > button').first.click()
    await page.wait_for_function("!document.getElementById('video')?.srcObject", timeout=15000)
    await asyncio.sleep(1)


async def main():
    with wave.open(str(OUT / 'audio-source.wav')) as source:
        reference_seconds = source.getnframes() / source.getframerate()
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path='/snap/chromium/current/usr/lib/chromium-browser/chrome',
            headless=args.headless, args=['--no-sandbox', '--autoplay-policy=no-user-gesture-required'])
        context = await browser.new_context(ignore_https_errors=True, locale='zh-TW', viewport={'width':1600,'height':1000})
        await context.add_init_script(INIT)
        page = await context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        report = {'reference_seconds':reference_seconds,'output_height':args.height,'headed':not args.headless,'turns':[]}
        try:
            await page.goto('https://localhost:3000',wait_until='networkidle')
            await settings(page, args.height)
            await page.reload(wait_until='networkidle')
            await page.locator('#btnViewSettings').click()
            await page.locator('#railTab-avatar').click()
            assert await page.locator('#avatar-output-height').input_value() == str(args.height)
            await page.locator('#btnViewConsole').click()
            await page.get_by_role('button',name='朗讀模式').click()
            await connect(page,{450:252,540:304}[args.height],args.height)
            if not args.playback_only:
                await settings(page,960,reconnect=True)
                assert await page.evaluate('document.getElementById("video").videoHeight') == 540
                await disconnect(page)
                await connect(page,540,960)
                report['resolution_switch_verified'] = True
                await settings(page,540,reconnect=True)
                await disconnect(page)
                await connect(page,304,540)
            await page.evaluate(CAPTURE)
            await asyncio.sleep(2)
            for index in range(3):
                before = await page.evaluate(STATS)
                await page.evaluate('probe.events=[];probe.frames=[];probe.chunks=[];probe.measuring=true;probe.recording=true')
                await page.locator('#viewConsole textarea.std-textarea').fill(TEXT)
                await page.locator('#viewConsole button.btn-send-main').click()
                await page.wait_for_function("probe.events.some(e=>e.type==='turn_committed')",timeout=60000)
                await asyncio.sleep(.5)
                await page.evaluate('probe.measuring=false;probe.recording=false')
                after = await page.evaluate(STATS)
                frames = await page.evaluate('probe.frames')
                events = await page.evaluate('probe.events')
                pcm = base64.b64decode(await page.evaluate(PCM))
                samples = np.frombuffer(pcm,dtype='<i2')
                active = np.flatnonzero(np.abs(samples.astype(np.int32))>65)
                span = (int(active[-1])-int(active[0])+1)/48000 if len(active) else 0
                gaps = [b['now']-a['now'] for a,b in zip(frames,frames[1:])]
                wall = (frames[-1]['now']-frames[0]['now'])/1000
                fps = (frames[-1]['presentedFrames']-frames[0]['presentedFrames'])/wall
                delta = {kind:{key:after.get(kind,{}).get(key,0)-before.get(kind,{}).get(key,0)
                    for key in ('concealedSamples','concealmentEvents','silentConcealedSamples','packetsLost',
                                'freezeCount','framesDropped','framesDecoded','totalSamplesReceived')}
                         for kind in ('audio','video')}
                result={'turn':index+1,'speech_span_seconds':round(span,3),'presented_fps':round(fps,2),
                        'max_display_gap_ms':round(max(gaps),2),'rtp_delta':delta}
                result['pass']=bool(len(active) and span<=reference_seconds*1.15
                    and delta['audio']['concealedSamples']==0 and delta['audio']['concealmentEvents']==0
                    and delta['video']['freezeCount']==0 and fps>=23 and max(gaps)<=120 and not errors)
                report['turns'].append(result)
                (OUT/f'{args.label}-turn-{index+1}-frames.json').write_text(json.dumps(frames,indent=2)+'\n')
                (OUT/f'{args.label}-turn-{index+1}-events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2)+'\n')
                with wave.open(str(OUT/f'{args.label}-turn-{index+1}.wav'),'wb') as out:
                    out.setnchannels(1);out.setsampwidth(2);out.setframerate(48000);out.writeframes(pcm)
                print(json.dumps(result),flush=True)
                await asyncio.sleep(1)
            report['page_errors']=errors
            report['pass']=all(turn['pass'] for turn in report['turns'])
            await page.screenshot(path=str(OUT/'console-playback.png'))
            (OUT/f'{args.label}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
            assert report['pass'],'Real console playback continuity gate failed'
        except Exception:
            await page.screenshot(path=str(OUT/'browser-error.png'))
            raise
        finally:
            try:
                await page.evaluate('probe.pcs.forEach(pc=>pc.close());probe.context?.close()')
            except Exception:
                pass
            await browser.close()


asyncio.run(main())
