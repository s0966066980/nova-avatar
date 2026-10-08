# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Capture synthetic avatar output only and gate Chromium audio continuity."""
import argparse
import asyncio
import base64
import json
from pathlib import Path
import wave
import numpy as np

from playwright.async_api import async_playwright

TEXT = '今天的測試會先確認聲音是否連續。接著比較嘴型推理造成的等待。最後記錄整段語音的播放時間。'
INIT = r"""
window.probe = {pcs: [], events: [], chunks: [], recording: false};
const Original = window.RTCPeerConnection;
window.RTCPeerConnection = class extends Original {
  constructor(...args) { super(...args); probe.pcs.push(this); }
  createDataChannel(...args) {
    const channel = super.createDataChannel(...args);
    channel.addEventListener('message', e => {
      try { probe.events.push({time:performance.now(), ...JSON.parse(e.data)}); } catch {}
    });
    return channel;
  }
};
// Text-only diagnostic: never acquire or persist microphone audio.
navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Diagnostic text-only', 'NotAllowedError'); };
"""
STATS = """async () => {
const stats=await probe.pcs.at(-1).getStats(); const out={};
for(const r of stats.values()) if(r.type==='inbound-rtp') out[r.kind]=r;
return out;
}"""

async def run(args):
    prefix = Path(args.output)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path='/snap/chromium/current/usr/lib/chromium-browser/chrome',
            headless=False,
            args=['--no-sandbox', '--autoplay-policy=no-user-gesture-required'],
        )
        context = await browser.new_context(ignore_https_errors=True, locale='zh-TW')
        await context.add_init_script(INIT)
        page = await context.new_page()
        try:
            await page.goto('https://localhost:3000',wait_until='networkidle')
            await page.get_by_role('button',name='朗讀模式').click()
            await page.evaluate("async()=>{const {useWebRTC}=await import('/src/composables/useWebRTC.js');probe.client=useWebRTC();probe.sessionid=await probe.client.startPlay();}")
            await page.wait_for_function("document.getElementById('video')?.videoWidth>0",timeout=25000)
            await page.evaluate(r"""async () => {
              const stream=document.getElementById('video').srcObject;
              probe.context=new AudioContext({sampleRate:48000});
              const code=`class Capture extends AudioWorkletProcessor {
                process(inputs) {
                  if(inputs[0]?.[0]) {
                    const pcm=new Float32Array(inputs[0][0]);
                    this.port.postMessage(pcm,[pcm.buffer]);
                  }
                  return true;
                }
              } registerProcessor('capture',Capture);`;
              const url=URL.createObjectURL(new Blob([code],{type:'text/javascript'}));
              await probe.context.audioWorklet.addModule(url); URL.revokeObjectURL(url);
              probe.source=probe.context.createMediaStreamSource(new MediaStream(stream.getAudioTracks()));
              probe.capture=new AudioWorkletNode(probe.context,'capture');
              probe.capture.port.onmessage=e=>{if(probe.recording)probe.chunks.push(e.data);};
              probe.source.connect(probe.capture); probe.capture.connect(probe.context.destination);
              await probe.context.resume();
            }""")
            await asyncio.sleep(1)
            before=await page.evaluate(STATS)
            await page.evaluate('probe.events=[];probe.chunks=[];probe.recording=true')
            request_text=TEXT if args.mode=='echo' else '請只用一個自然的短段落介紹台灣，不用看板。'
            await page.evaluate("async ([text,mode])=>{const r=await fetch('/human',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sessionid:probe.sessionid,type:mode,interrupt:true,text})});const data=await r.json();if(!r.ok||data.code===-1)throw new Error(data.msg||String(r.status));}",[request_text,args.mode])
            await page.wait_for_function("probe.events.some(e=>e.type==='turn_committed')",timeout=90000)
            await asyncio.sleep(.7)
            await page.evaluate('probe.recording=false')
            after=await page.evaluate(STATS)
            result={'mode':args.mode,'text':request_text,'events':await page.evaluate('probe.events'),'audio':{},'video':{}}
            result['jitter_buffer_targets']=await page.evaluate("Object.fromEntries(probe.pcs.at(-1).getReceivers().map(r=>[r.track.kind,r.jitterBufferTarget]))")
            for kind in ('audio','video'):
                for key in ('concealedSamples','concealmentEvents','silentConcealedSamples','totalSamplesReceived',
                            'removedSamplesForAcceleration','insertedSamplesForDeceleration','packetsLost',
                            'freezeCount','totalFreezesDuration','framesDecoded','framesDropped'):
                    if key in after.get(kind,{}):
                        result[kind][key]=after[kind][key]-before.get(kind,{}).get(key,0)
            encoded=await page.evaluate(r"""() => {
              const length=probe.chunks.reduce((sum,c)=>sum+c.length,0);
              const pcm=new Int16Array(length);let offset=0;
              for(const chunk of probe.chunks)for(const sample of chunk)pcm[offset++]=Math.round(Math.max(-1,Math.min(1,sample))*32767);
              const bytes=new Uint8Array(pcm.buffer);let str='';
              for(let i=0;i<bytes.length;i+=32768)str+=String.fromCharCode(...bytes.subarray(i,i+32768));
              return btoa(str);
            }""")
            pcm=base64.b64decode(encoded)
            with wave.open(str(prefix.with_suffix('.wav')),'wb') as out:
                out.setnchannels(1);out.setsampwidth(2);out.setframerate(48000);out.writeframes(pcm)
            result['capture_seconds']=len(pcm)/96000
            samples=np.frombuffer(pcm,dtype='<i2')
            active=np.flatnonzero(np.abs(samples.astype(np.int32))>65)
            result['speech_span_seconds']=(int(active[-1])-int(active[0])+1)/48000 if len(active) else 0
            source=prefix.parent/'audio-source.wav'
            if args.mode=='chat':
                import edge_tts
                import av
                played=next(e['played_text'] for e in result['events'] if e.get('type')=='turn_committed')
                result['played_text']=played
                source=prefix.with_name(prefix.name+'-source').with_suffix('.wav')
                mp3=source.with_suffix('.mp3')
                await edge_tts.Communicate(played,'zh-TW-HsiaoChenNeural').save(str(mp3))
                with av.open(str(mp3)) as container:
                    decoded=[f for f in container.decode(audio=0)]
                reference=np.concatenate([f.to_ndarray().reshape(-1) for f in decoded])
                with wave.open(str(source),'wb') as out:
                    out.setnchannels(1);out.setsampwidth(2);out.setframerate(decoded[0].sample_rate)
                    out.writeframes(np.clip(reference*32767,-32768,32767).astype('<i2').tobytes())
            if source.exists():
                with wave.open(str(source)) as reference:
                    result['reference_seconds']=reference.getnframes()/reference.getframerate()
            result['pass']=bool(len(active) and result['audio'].get('concealedSamples',0)==0
                and result['audio'].get('concealmentEvents',0)==0
                and result['speech_span_seconds']<=result.get('reference_seconds',11)*1.15)
            prefix.with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps({k:v for k,v in result.items() if k!='events'},ensure_ascii=False),flush=True)
            assert result['pass'],'Browser synthesized speech has missing/concealed audio or inserted playback gaps'
        except Exception:
            messages=await page.locator('.notification, .notification-message').all_text_contents()
            print('UI notifications:',messages,flush=True)
            raise
        finally:
            try:
                await page.evaluate("async()=>{probe.client?.stopPlay(); if(probe.context)await probe.context.close();}")
            except Exception:
                pass
            await browser.close()

parser=argparse.ArgumentParser()
parser.add_argument('--output',required=True)
parser.add_argument('--mode',choices=('echo','chat'),default='echo')
asyncio.run(run(parser.parse_args()))
