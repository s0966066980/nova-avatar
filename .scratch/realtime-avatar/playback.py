# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Fixed-answer WebRTC replay with optional profiling and isolated LLM load."""
import argparse,asyncio,json,sys,time,threading,importlib.util,functools,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import cv2,numpy as np
import torch
from aiortc import RTCPeerConnection,RTCConfiguration,RTCRtpSender
from src.config.loader import load_config
from src.avatars.musetalk.avatar import load_model,load_avatar,MuseTalkAvatar,warm_up
from src.avatars.musetalk.vae_acceleration import TensorRTVAEDecoder
from src.scene.service import scene_service
from src.utils.webrtc import HumanPlayer

class Background:
 def frame(self,width,height):return np.full((height,width,3),80,np.uint8)
 def close(self):pass

async def run(args):
 config=load_config(args.config);config.sessionid=765432;config.customopt=[]
 config.model.batch_size=args.batch_size
 config.video.max_height=args.height
 config.tts.type='edgetts'
 if args.cpu_threads:torch.set_num_threads(args.cpu_threads)
 if args.production_model:
  from src.avatars.factory import prepare_avatar_model
  model,avatar_data=prepare_avatar_model(config)
  args.tiny=bool(config.model.musetalk.tiny_vae_path)
  args.unet_engine=config.model.musetalk.unet_engine_path
 else:
  model=load_model(tiny_vae_path='.local/jetson/taesd' if args.tiny else '',
                   unet_engine_path=args.unet_engine)
  if args.engine:
   model=(TensorRTVAEDecoder(model[0],args.engine),*model[1:])
  avatar_data=load_avatar(config.model.avatar_id)
  warm_up(config.model.batch_size,model)
 profile={};cuda_events=[];profile_active=threading.Event()
 def instrument(obj,name,label,gpu=False):
  original=getattr(obj,name)
  @functools.wraps(original)
  def measured(*a,**kw):
   if not profile_active.is_set():return original(*a,**kw)
   start=time.perf_counter()
   if gpu:
    before,after=torch.cuda.Event(enable_timing=True),torch.cuda.Event(enable_timing=True)
    before.record()
   result=original(*a,**kw)
   if gpu:
    after.record();cuda_events.append((label,before,after,int(a[0].shape[0])))
   else:profile.setdefault(label,[]).append((time.perf_counter()-start)*1000)
   return result
  setattr(obj,name,measured)
 if args.profile:
  instrument(model[1].model,'forward','unet_gpu',True)
  instrument(model[0],'decode_latents','vae_decode_host')
  instrument(model[4],'audio2feat','whisper_features_host')
  import src.scene.service as scene_module
  instrument(scene_module,'chroma_composite','chroma_composite_host')
  from aiortc.codecs.h264 import H264Encoder
  instrument(H264Encoder,'encode','h264_encode_host')
 avatar=MuseTalkAvatar(config,model,avatar_data)
 if args.legacy_tts_loop:
  spec=importlib.util.spec_from_file_location('baseline_edge','.scratch/reply-latency/edge-baseline.py')
  baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
  avatar.tts.close_worker();avatar.tts=baseline.EdgeTTS(config,avatar)
 scene_service._source=Background()
 sender=RTCPeerConnection(RTCConfiguration(iceServers=[]))
 receiver=RTCPeerConnection(RTCConfiguration(iceServers=[]))
 connected=asyncio.Event();completed=asyncio.Event();cancelled=threading.Event()
 send_audio_times=[];received_audio_times=[];received_video_times=[];pcm_active=0
 sent_samples=0;source_samples=0;first_source_time=None;sample_sequences={};video_sequences={};alignment={};stale_drops={};drainers=[]
 ended_fragments=set();committed_fragments=set()
 captured=[];stress_metrics=[];stress_started=threading.Event();stress_errors=[]
 phrases=['今天的測試會先確認聲音是否連續。','接著比較嘴型推理造成的等待。','最後記錄整段語音的播放時間。']
 if args.single_reply:phrases=[''.join(phrases)]
 active_started=asyncio.Event();started_at=None;last_fragment=len(phrases)-1;feeder_pending=threading.Event()
 expected_samples=int(args.seconds*16000)//320*320
 def match(key):
  if key in sample_sequences and key in video_sequences:
   alignment.setdefault(key,abs(sample_sequences[key]-video_sequences[key]))
 def on_audio(event,active):
  nonlocal sent_samples
  if event and event.get('turn_id')=='probe':
   key=(event.get('fragment_sequence'),event.get('media_sequence'));sample_sequences.setdefault(key,time.monotonic());match(key)
   send_audio_times.append(time.monotonic());sent_samples+=320
   if active:
    active_started.set();committed_fragments.add(event.get('fragment_sequence'))
   if event.get('fragment_end'):
    ended_fragments.add(event.get('fragment_sequence'))
    if not (args.speech or args.pcm_file) or event.get('fragment_sequence')==last_fragment:completed.set()
 def on_drop(stage,reason):
  key=stage+':'+reason;stale_drops[key]=stale_drops.get(key,0)+1
 class Player(HumanPlayer):
  def notify_media_timing(self,kind,seconds,event=None):
   super().notify_media_timing(kind,seconds,event)
   if kind=='video' and event and event.get('turn_id')=='probe':
    key=(event.get('fragment_sequence'),event.get('media_sequence'));video_sequences.setdefault(key,time.monotonic());match(key)
 player=Player(avatar,on_audio_frame=on_audio,on_stale_drop=on_drop)
 avatar.configure_media_fence(media_guard=lambda *_:not cancelled.is_set(),on_stale_drop=on_drop,
   fragment_playback_committed=lambda e:e.get('fragment_sequence') in committed_fragments,
   fragment_playback_ended=lambda e:e.get('fragment_sequence') in ended_fragments)
 original_put=avatar.put_audio_frame
 def counted_put(chunk,event):
  nonlocal source_samples,first_source_time
  if first_source_time is None:first_source_time=time.monotonic()
  accepted=original_put(chunk,event)
  if accepted:source_samples+=len(chunk)
  if accepted and args.capture_pcm:captured.append((chunk.copy(),dict(event or {})))
  return accepted
 avatar.put_audio_frame=counted_put
 if args.independent:avatar.configure_audio_output(player.audio,asyncio.get_running_loop())
 sender.addTrack(player.audio);sender.addTrack(player.video)
 codecs=RTCRtpSender.getCapabilities('video').codecs
 preferences=[c for c in codecs if c.name in ('H264','rtx')]
 for t in sender.getTransceivers():
  if t.kind=='video':t.setCodecPreferences(preferences)
 async def drain(track):
  nonlocal pcm_active
  try:
   while True:
    frame=await track.recv()
    if started_at is None:continue
    if track.kind=='audio':
     data=frame.to_ndarray()
     if np.max(np.abs(data.astype(np.int32)))>30:
      pcm_active+=1;received_audio_times.append(time.monotonic())
    else:received_video_times.append(time.monotonic())
  except Exception:pass
 @receiver.on('track')
 def track(track):drainers.append(asyncio.create_task(drain(track)))
 @sender.on('connectionstatechange')
 async def state():
  if sender.connectionState=='connected':connected.set()
 offer=await sender.createOffer();await sender.setLocalDescription(offer)
 await receiver.setRemoteDescription(sender.localDescription)
 answer=await receiver.createAnswer();await receiver.setLocalDescription(answer)
 await sender.setRemoteDescription(receiver.localDescription)
 await asyncio.wait_for(connected.wait(),10)
 await asyncio.sleep(.5)
 # Smooth, non-silent deterministic PCM exercises the real mouth and transport
 # paths without a remote TTS or LLM introducing unrelated latency.
 samples=np.arange(expected_samples,dtype=np.float32)
 pcm=(np.sin(samples*2*np.pi*220/16000)*.1).astype(np.float32)
 cached=None
 if args.pcm_file:
  with np.load(args.pcm_file,allow_pickle=False) as fixture:
   pcm=fixture['pcm'];events=json.loads(str(fixture['events']))
  cached=[]
  fragment_count=max(event['fragment_sequence'] for event in events)+1
  for repeat in range(args.repeat):
   cached.extend([dict(event,fragment_sequence=event['fragment_sequence']+repeat*fragment_count) for event in events])
  pcm=np.tile(pcm,args.repeat);expected_samples=len(pcm)
  last_fragment=max(event['fragment_sequence'] for event in cached)
 if args.paced:
  original_pending=avatar.tts.has_pending_work
  avatar.tts.has_pending_work=lambda:feeder_pending.is_set() or original_pending()
 def stress():
  while not cancelled.is_set():
   start=time.monotonic();first=None;tokens=0
   payload={'model':args.llm_model,'messages':[{'role':'user','content':'請詳細介紹台灣的自然環境與文化特色。'}],
            'max_tokens':512,'stream':True,'temperature':0,'ignore_eos':True}
   request=urllib.request.Request(args.stress_server+'/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
   try:
    with urllib.request.urlopen(request,timeout=90) as response:
     for line in response:
      if cancelled.is_set():break
      if not line.startswith(b'data: ') or line.strip()==b'data: [DONE]':continue
      chunk=json.loads(line[6:]);choices=chunk.get('choices',[])
      if choices and choices[0].get('delta',{}).get('content'):
       tokens+=1
       if first is None:first=time.monotonic();stress_started.set()
    stress_metrics.append({'started_at':start,'first_content_seconds':first-start if first else None,
                           'content_chunks':tokens,'wall_seconds':time.monotonic()-start,'cancelled':cancelled.is_set()})
   except Exception as error:
    stress_errors.append(type(error).__name__);stress_started.set();return
 stress_task=None
 if args.stress_server:
  stress_task=asyncio.create_task(asyncio.to_thread(stress))
  if not await asyncio.to_thread(stress_started.wait,20):raise RuntimeError('LLM generation did not start')
  if stress_errors:raise RuntimeError('LLM load request failed: '+str(stress_errors))
 def feed():
  profile_active.set();feeder_pending.set();feed_started=time.monotonic()
  if cached is not None:
   for i,event in enumerate(cached):
    if cancelled.is_set():return
    if args.paced:
     delay=feed_started+i*.02-time.monotonic()
     if delay>0:time.sleep(delay)
    if not avatar.put_audio_frame(pcm[i*320:(i+1)*320],event):return
   feeder_pending.clear();return
  if args.speech:
   # Every fragment is already known, matching the user's completed-LLM case.
   for i,text in enumerate(phrases):
    avatar.put_msg_txt(text,{'turn_id':'probe','generation':1,'fragment_sequence':i})
   return
  for i in range(expected_samples//320):
   if cancelled.is_set():return
   event={'turn_id':'probe','generation':1,'fragment_sequence':0,'media_sequence':i}
   if i==0:event.update(status='start',fragment_start=True)
   if i==expected_samples//320-1:event.update(status='end',fragment_end=True)
   if not avatar.put_audio_frame(pcm[i*320:(i+1)*320],event):return
 started_at=time.monotonic()
 measurement_started_epoch=time.time()
 producer=asyncio.create_task(asyncio.to_thread(feed))
 try:
  await asyncio.wait_for(completed.wait(),120 if args.speech or cached is not None else args.seconds*5+8)
  await asyncio.sleep(.3)
 except asyncio.TimeoutError:pass
 cancelled.set()
 measurement_ended_epoch=time.time()
 profile_active.clear()
 if args.capture_pcm:
  np.savez(args.capture_pcm,pcm=np.concatenate([x[0] for x in captured]),events=json.dumps([x[1] for x in captured]))
 report={'height_limit':args.height,'independent_audio':args.independent,'engine':bool(args.engine),
         'speech':args.speech,'single_reply':args.single_reply,'legacy_tts_loop':args.legacy_tts_loop,
         'expected_pcm_seconds':source_samples/16000 if args.speech else expected_samples/16000,'sent_pcm_seconds':sent_samples/16000,
         'completion':completed.is_set(),'first_audio_seconds':round(send_audio_times[0]-started_at,4) if send_audio_times else None,
         'active_playback_wall_seconds':round(send_audio_times[-1]-send_audio_times[0]+.02,4) if send_audio_times else None,
         'audio_release_max_gap_ms':round(max(np.diff(send_audio_times))*1000,2) if len(send_audio_times)>1 else None,
         'received_audio_max_gap_ms':round(max(np.diff(received_audio_times))*1000,2) if len(received_audio_times)>1 else None,
         'received_video_frames':len(received_video_times),'av_matched_samples':len(alignment),
         'av_wall_offset_p95_ms':round(float(np.percentile(list(alignment.values()),95))*1000,2) if alignment else None,
         'stale_drops':stale_drops,'vae_failed':getattr(model[0],'_failed',False)}
 if stress_task:await asyncio.wait_for(stress_task,10)
 report.update(batch_size=args.batch_size,cached_pcm=bool(cached),llm_stress=bool(args.stress_server),llm_requests=stress_metrics,llm_errors=stress_errors,tiny=args.tiny,channels_last=args.channels_last,unet_engine=bool(args.unet_engine),unet_failed=getattr(model[1].model,'_failed',False),av_match_key='fragment_sequence,media_sequence',
               production_model_loader=args.production_model,effective_llm_provider=config.llm.provider,cpu_threads=torch.get_num_threads(),measurement_started_epoch=measurement_started_epoch,measurement_ended_epoch=measurement_ended_epoch)
 if args.profile:
  torch.cuda.synchronize()
  batches={}
  for label,before,after,n in cuda_events:
   profile.setdefault(label,[]).append(before.elapsed_time(after));batches.setdefault(label,[]).append(n)
  report['profile_ms']={k:{'count':len(v),'p50':round(float(np.median(v)),3),'p95':round(float(np.percentile(v,95)),3),
                          'first_values': [round(float(x),3) for x in v[:5]],'total':round(float(sum(v)),3)} for k,v in profile.items()}
  report['unet_batch_sizes']=batches.get('unet_gpu',[])
 report['audio_continuity_pass']=bool(report['completion'] and abs(report['expected_pcm_seconds']-report['sent_pcm_seconds'])<.001 and report['audio_release_max_gap_ms'] is not None and report['audio_release_max_gap_ms']<60 and (args.speech or args.pcm_file or (report['received_audio_max_gap_ms'] is not None and report['received_audio_max_gap_ms']<100)))
 if args.speech or args.pcm_file:report['receiver_gap_note']='Active-voice gaps include natural pauses; continuity gate uses tagged PCM and completeness.'
 report['av_gate_pass']=bool(len(alignment)>=5 and report['av_wall_offset_p95_ms']<=80)
 if args.speech:expected_samples=source_samples
 report['first_pcm_to_audio_seconds']=round(send_audio_times[0]-first_source_time,4) if send_audio_times and first_source_time else None
 report['unet_adapter']=type(model[1].model).__name__
 report['decoder_adapter']=type(model[0]).__name__
 report['unique_mouth_frames']=len(video_sequences)
 report['mouth_frame_coverage']=round(len(video_sequences)/(expected_samples/640),4)
 report['paced_input']=args.paced
 report['repeat']=args.repeat
 report['realtime_gate_pass']=bool(report['audio_continuity_pass'] and report['av_gate_pass'] and report['mouth_frame_coverage']>=.95 and report['active_playback_wall_seconds']<=report['expected_pcm_seconds']+.1 and report['first_pcm_to_audio_seconds']<=1.0 and not report['unet_failed'] and not report['vae_failed'])
 report['audio_gap_events']=[dict(before=list(sample_sequences)[i],after=list(sample_sequences)[i+1],gap_ms=round(float(gap)*1000,2)) for i,gap in enumerate(np.diff(send_audio_times)) if gap>.05]
 report['audio_release_largest_gaps_ms']=sorted([round(float(gap)*1000,2) for gap in np.diff(send_audio_times)],reverse=True)[:10]
 Path(args.output).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
 # Invalidate pending generations before stopping the render and TTS threads.
 avatar.stop_audio_output();avatar.flush_talk()
 await sender.close();await receiver.close()
 for task in drainers:task.cancel()
 await asyncio.gather(*drainers,return_exceptions=True)
 await asyncio.wait_for(producer,2)
 return report
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--config',default='config/config_jetson.yaml');parser.add_argument('--production-model',action='store_true');parser.add_argument('--height',type=int,default=0);parser.add_argument('--engine',default='');parser.add_argument('--independent',action='store_true');parser.add_argument('--speech',action='store_true');parser.add_argument('--single-reply',action='store_true');parser.add_argument('--legacy-tts-loop',action='store_true');parser.add_argument('--seconds',type=float,default=3);parser.add_argument('--output',required=True)
 parser.add_argument('--batch-size',type=int,default=8);parser.add_argument('--profile',action='store_true');parser.add_argument('--capture-pcm',default='');parser.add_argument('--pcm-file',default='');parser.add_argument('--stress-server',default='');parser.add_argument('--llm-model',default='Qwen3.5-4B-UD-Q4_K_XL')
 parser.add_argument('--tiny',action='store_true');parser.add_argument('--channels-last',action='store_true')
 parser.add_argument('--unet-engine',default='');parser.add_argument('--cpu-threads',type=int,default=0);parser.add_argument('--repeat',type=int,default=1);parser.add_argument('--paced',action='store_true')
 asyncio.run(run(parser.parse_args()))
