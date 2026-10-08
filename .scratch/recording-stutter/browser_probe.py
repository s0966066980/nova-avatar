# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Measure fixed read-aloud in headed Chromium, including presented pixels."""
import asyncio
import json
import os
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(os.getenv('NOVA_PROBE_OUTPUT_DIR', '.scratch/recording-stutter'))
OUT.mkdir(parents=True, exist_ok=True)
TEXT = '今天的測試會先確認聲音是否連續。接著比較嘴型推理造成的等待。最後記錄整段語音的播放時間。'
INIT = r"""
window.probe = {pcs: [], events: [], frames: [], measuring: false, targets: {}};
const Original = window.RTCPeerConnection;
window.RTCPeerConnection = class extends Original {
  constructor(...args) {
    super(...args); probe.pcs.push(this);
    this.addEventListener('track', e => {
      setTimeout(() => { probe.targets[e.track.kind] = e.receiver.jitterBufferTarget; }, 0);
    });
  }
  createDataChannel(...args) {
    const channel = super.createDataChannel(...args);
    channel.addEventListener('message', e => {
      try { probe.events.push({time: performance.now(), ...JSON.parse(e.data)}); } catch {}
    });
    return channel;
  }
};
"""
STATS = """async () => {
const stats = await probe.pcs.at(-1).getStats(); const out = {};
for (const r of stats.values()) if(r.type === 'inbound-rtp') out[r.kind] = r;
return out;
}"""


async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path='/snap/chromium/current/usr/lib/chromium-browser/chrome',
            headless=False,
            args=['--no-sandbox', '--autoplay-policy=no-user-gesture-required',
                  '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'],
        )
        context = await browser.new_context(ignore_https_errors=True, locale='zh-TW', viewport={'width': 1600, 'height': 1000})
        diagnostic = INIT
        if os.getenv('NOVA_PROBE_NO_MICROPHONE') == '1':
            diagnostic += "navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('Diagnostic text-only','NotAllowedError');};"
        await context.add_init_script(diagnostic)
        page = await context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        try:
            await page.goto('https://localhost:3000', wait_until='networkidle')
            print('Loaded console', flush=True)
            await page.get_by_role('button', name='朗讀模式').click()
            print('Selected read-aloud', flush=True)
            await page.locator('.stage-footer-actions > button').first.click(timeout=30000)
            print('Requested connection', flush=True)
            await page.wait_for_function("document.getElementById('video')?.videoWidth > 0", timeout=60000)
            await page.evaluate(r"""() => {
              const video = document.getElementById('video');
              const canvas = document.createElement('canvas'); canvas.width=64; canvas.height=64;
              const ctx = canvas.getContext('2d', {willReadFrequently: true}); let previous=null;
              function tick(now, meta) {
                if(probe.measuring) {
                  ctx.drawImage(video, video.videoWidth*.25, video.videoHeight*.20,
                    video.videoWidth*.5, video.videoHeight*.3, 0, 0, 64, 64);
                  const data=ctx.getImageData(0,0,64,64).data;
                  let diff=0; if(previous) for(let i=0;i<data.length;i+=4)
                    diff+=Math.abs(data[i]-previous[i])+Math.abs(data[i+1]-previous[i+1])+Math.abs(data[i+2]-previous[i+2]);
                  probe.frames.push({now, mediaTime:meta.mediaTime, presentedFrames:meta.presentedFrames,
                    diff:previous ? diff/(64*64*3) : 255}); previous=data;
                } else previous=null;
                video.requestVideoFrameCallback(tick);
              }
              video.requestVideoFrameCallback(tick);
            }""")
            await asyncio.sleep(2)
            turns = []
            for turn in range(3):
                before = await page.evaluate(STATS)
                await page.evaluate('probe.frames=[]; probe.events=[]; probe.measuring=true')
                await page.locator('#viewConsole textarea.std-textarea').fill(TEXT)
                await page.locator('#viewConsole button.btn-send-main').click()
                await page.wait_for_function("probe.events.some(e => e.type === 'turn_committed')", timeout=45000)
                await asyncio.sleep(.5)
                await page.evaluate('probe.measuring=false')
                after = await page.evaluate(STATS)
                frames = await page.evaluate('probe.frames')
                events = await page.evaluate('probe.events')
                gaps = [b['now']-a['now'] for a,b in zip(frames,frames[1:])]
                still_start = None
                max_still = 0
                for i,f in enumerate(frames):
                    if f['diff'] < .1:
                        if still_start is None: still_start = frames[max(0,i-1)]['now']
                        max_still = max(max_still,f['now']-still_start)
                    else: still_start = None
                delta = {}
                for kind in ('audio','video'):
                    delta[kind] = {key: value-before.get(kind,{}).get(key,0)
                        for key,value in after.get(kind,{}).items()
                        if isinstance(value,(int,float)) and key not in ('timestamp','ssrc')}
                wall = (frames[-1]['now']-frames[0]['now'])/1000
                presented = frames[-1]['presentedFrames'] - frames[0]['presentedFrames']
                result = {'turn':turn+1,'callback_samples':len(frames),'presented_frames':presented,'presented_fps':presented/wall,
                    'max_display_gap_ms':max(gaps),'max_near_identical_face_ms':max_still,
                    'rtp_delta':delta,'events':events,'frame_samples':frames,'video_quality':await page.evaluate("document.getElementById('video').getVideoPlaybackQuality().toJSON?.() || ({totalVideoFrames:document.getElementById('video').getVideoPlaybackQuality().totalVideoFrames,droppedVideoFrames:document.getElementById('video').getVideoPlaybackQuality().droppedVideoFrames})")}
                result['pass'] = result['presented_fps'] >= 23 and max(gaps) <= 120 and max_still <= 250 and delta['audio'].get('concealedSamples',0) == 0 and delta['video'].get('freezeCount',0) == 0 and not errors
                turns.append(result)
                print(json.dumps({k:v for k,v in result.items() if k not in ('events','rtp_delta','frame_samples')},ensure_ascii=False),flush=True)
                await asyncio.sleep(1)
            await page.screenshot(path=str(OUT/'browser-after.png'))
            report = {'headed': True,'video_dimensions':await page.evaluate('({width:document.getElementById("video").videoWidth,height:document.getElementById("video").videoHeight})'),'text':TEXT,'jitter_buffer_targets':await page.evaluate('probe.targets'),
                      'turns':turns,'page_errors':errors,'pass':all(t['pass'] for t in turns)}
            (OUT/'browser-playback.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
            assert report['pass'], 'Browser continuity gate failed'
        except Exception:
            await page.screenshot(path=str(OUT/'browser-error.png'))
            print('Buttons:', await page.locator('button').all_text_contents(), flush=True)
            raise
        finally:
            try:
                await page.evaluate('probe.pcs.forEach(pc => pc.close())')
            except Exception:
                pass
            await browser.close()


asyncio.run(run())
