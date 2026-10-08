# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Real local API -> LFM/TTS/avatar -> headed Chromium WebRTC/PCM.

Capture synthetic avatar audio only. Deliberately no canvas readback per frame.
"""
import argparse,asyncio,base64,json,ssl,time,urllib.request,wave
from pathlib import Path
import numpy as np
import av,edge_tts
from playwright.async_api import async_playwright
TEXT='今天的測試會先確認聲音是否連續。接著比較嘴型推理造成的等待。最後記錄整段語音的播放時間。'
QUESTIONS=['你好！請簡短自我介紹','請整理 Nova Avatar 三大核心技術優勢並輸出看板','請列出系統安裝部署四步驟','今天台北天氣如何？']
INIT=r'''
window.probe={pcs:[],events:[],frames:[],chunks:[],recording:false};
const Original=window.RTCPeerConnection;
window.RTCPeerConnection=class extends Original {
 constructor(...args){super(...args);probe.pcs.push(this);}
 createDataChannel(...args){const c=super.createDataChannel(...args);c.addEventListener('message',e=>{try{probe.events.push({time:performance.now(),...JSON.parse(e.data)});}catch{}});return c;}
};
navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('Synthetic text-only diagnostic','NotAllowedError');};
'''
STATS='''async()=>{const out={};for(const r of (await probe.pcs.at(-1).getStats()).values())if(r.type==='inbound-rtp')out[r.kind]=r;return out;}'''
async def run(args):
 out=Path(args.output);out.mkdir(parents=True,exist_ok=True);rows=[]
 async with async_playwright() as p:
  browser=await p.chromium.launch(executable_path='/snap/chromium/current/usr/lib/chromium-browser/chrome',headless=False,args=['--no-sandbox','--autoplay-policy=no-user-gesture-required'])
  context=await browser.new_context(ignore_https_errors=True,locale='zh-TW',viewport={'width':1600,'height':1000});await context.add_init_script(INIT);page=await context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  try:
   await page.goto('https://localhost:3000',wait_until='networkidle')
   await page.get_by_role('button',name='朗讀模式').click()
   await page.evaluate("async()=>{const{useWebRTC}=await import('/src/composables/useWebRTC.js');probe.client=useWebRTC();probe.sessionid=await probe.client.startPlay();}")
   await page.wait_for_function("document.getElementById('video')?.videoWidth>0",timeout=60000)
   dimensions=await page.evaluate("({width:document.getElementById('video').videoWidth,height:document.getElementById('video').videoHeight})")
   assert dimensions=={'width':args.height*9//16,'height':args.height},dimensions
   await page.evaluate(r'''async()=>{
    const v=document.getElementById('video');
    function tick(now,m){if(probe.recording)probe.frames.push({now,mediaTime:m.mediaTime,presentedFrames:m.presentedFrames});v.requestVideoFrameCallback(tick);}v.requestVideoFrameCallback(tick);
    probe.context=new AudioContext({sampleRate:48000});
    const code=`class Capture extends AudioWorkletProcessor{process(inputs){if(inputs[0]?.[0]){const a=new Float32Array(inputs[0][0]);this.port.postMessage(a,[a.buffer]);}return true;}}registerProcessor('capture',Capture);`;
    const url=URL.createObjectURL(new Blob([code],{type:'text/javascript'}));await probe.context.audioWorklet.addModule(url);URL.revokeObjectURL(url);
    probe.source=probe.context.createMediaStreamSource(new MediaStream(v.srcObject.getAudioTracks()));probe.capture=new AudioWorkletNode(probe.context,'capture');
    probe.capture.port.onmessage=e=>{if(probe.recording)probe.chunks.push(e.data);};
    const silent=probe.context.createGain();silent.gain.value=0;probe.source.connect(probe.capture);probe.capture.connect(silent);silent.connect(probe.context.destination);await probe.context.resume();
   }''')
   await asyncio.sleep(2)
   for i,(mode,text) in enumerate([('echo',TEXT)]*3+[('chat',q) for q in QUESTIONS]):
    before=await page.evaluate(STATS)
    await page.evaluate('probe.events=[];probe.frames=[];probe.chunks=[];probe.recording=true;probe.start=performance.now()')
    row={'turn':i+1,'mode':mode,'text':text}
    try:
     await page.evaluate("async([text,type])=>{const r=await fetch('/human',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sessionid:probe.sessionid,type,interrupt:true,text})});const j=await r.json();if(!r.ok||j.code===-1)throw new Error(j.msg||String(r.status));}",[text,mode])
     await page.wait_for_function("probe.events.some(e=>e.type==='turn_committed')",timeout=120000)
     await asyncio.sleep(.7)
     await page.evaluate('probe.recording=false');after=await page.evaluate(STATS)
     events=await page.evaluate('probe.events');frames=await page.evaluate('probe.frames');row['events']=events
     row['played_text']=next(e.get('played_text','') for e in events if e['type']=='turn_committed')
     row['metrics']=next((e['metrics'] for e in events if e['type']=='turn_metrics'),{})
     row['audio']={};row['video']={}
     for kind in ('audio','video'):
      for key in ('concealedSamples','concealmentEvents','silentConcealedSamples','packetsLost','freezeCount','totalFreezesDuration','framesDecoded','framesDropped'):
       if key in after.get(kind,{}):row[kind][key]=after[kind][key]-before.get(kind,{}).get(key,0)
     encoded=await page.evaluate(r'''()=>{const pcm=new Int16Array(probe.chunks.reduce((s,c)=>s+c.length,0));let o=0;for(const c of probe.chunks)for(const a of c)pcm[o++]=Math.round(Math.max(-1,Math.min(1,a))*32767);const bytes=new Uint8Array(pcm.buffer);let s='';for(let i=0;i<bytes.length;i+=32768)s+=String.fromCharCode(...bytes.subarray(i,i+32768));return btoa(s);}''')
     pcm=base64.b64decode(encoded)
     with wave.open(str(out/f'turn-{i+1}.wav'),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(48000);f.writeframes(pcm)
     active=np.flatnonzero(np.abs(np.frombuffer(pcm,dtype='<i2').astype(np.int32))>65)
     row['first_played_audio_seconds']=float(active[0]/48000) if len(active) else None
     row['speech_span_seconds']=float((active[-1]-active[0]+1)/48000) if len(active) else 0
     row['capture_seconds']=len(pcm)/96000
     if row['played_text']:
      mp3=out/f'turn-{i+1}-source.mp3';await edge_tts.Communicate(row['played_text'],'zh-TW-HsiaoChenNeural').save(str(mp3))
      with av.open(str(mp3)) as c:
       decoded=list(c.decode(audio=0))
       row['reference_seconds']=sum(f.samples/f.sample_rate for f in decoded)
     row['speech_span_ratio']=row['speech_span_seconds']/row.get('reference_seconds',1)
     starts=[e['time'] for e in events if e['type']=='speaking_start'];ends=[e['time'] for e in events if e['type']=='speaking_end']
     if starts and ends:speaking=[f for f in frames if starts[0]<=f['now']<=ends[-1]+160]
     else:speaking=frames
     if len(speaking)>1:
      gaps=[b['now']-a['now'] for a,b in zip(speaking,speaking[1:])];wall=(speaking[-1]['now']-speaking[0]['now'])/1000
      row['presented_fps']=(speaking[-1]['presentedFrames']-speaking[0]['presentedFrames'])/wall;row['max_display_gap_ms']=max(gaps)
     else:row['presented_fps']=0;row['max_display_gap_ms']=None
     boards=[e for e in events if e['type'] in ['assistant_board','board_begin','board_item','board_end']];row['board_events']=boards
     # Voice delivery and smoothness are distinct gates. A recovery message
     # does not count as a successfully answered example question.
     row['item_count']=sum(e['type']=='board_item' for e in boards)
     row['answer_pass']=bool(row['played_text'] and '回覆格式異常' not in row['played_text']) and (row['item_count']==4 if '四步驟' in text else row['item_count']==3 if '三大' in text else True)
     row['audio_pass']=bool(len(active) and row['audio'].get('concealedSamples',0)==0 and row['audio'].get('concealmentEvents',0)==0 and row['speech_span_ratio']<=1.15)
     row['video_pass']=row['presented_fps']>=23 and (row['max_display_gap_ms'] or 1e6)<=120 and row['video'].get('freezeCount',0)==0
     row['pass']=row['answer_pass'] and row['audio_pass'] and row['video_pass'] and not errors
     row['frame_samples']=frames
    except Exception as exc:
     await page.evaluate('probe.recording=false');row['error']=type(exc).__name__;row['pass']=False;row['events']=await page.evaluate('probe.events')
    rows.append(row)
    report={'video_dimensions':dimensions,'mode':'headed Chromium, text only, production receiver settings','rows':rows,'page_errors':errors,'pass':all(r['pass'] for r in rows)}
    (out/'playback.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in row.items() if k not in ['events','frame_samples','board_events']},ensure_ascii=False),flush=True)
    await asyncio.sleep(1)
   await page.screenshot(path=str(out/'stage.png'))
   assert report['pass'],'One or more real playback gates failed'
  finally:
   try:await page.evaluate('async()=>{probe.client?.stopPlay();if(probe.context)await probe.context.close();}')
   except Exception:pass
   await browser.close()
parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--height',type=int,required=True)
asyncio.run(run(parser.parse_args()))
