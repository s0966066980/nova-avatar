# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Isolated real WebRTC experiment; no production server or LLM is changed."""
import argparse,asyncio,json,sys,time,threading,importlib.util
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import cv2,numpy as np
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
 config=load_config('config/config_jetson.yaml');config.sessionid=765432;config.customopt=[]
 config.video.max_height=args.height
 config.tts.type='edgetts'
 model=load_model()
 if args.engine:
  model=(TensorRTVAEDecoder(model[0],args.engine),*model[1:])
 avatar_data=load_avatar(config.model.avatar_id)
 warm_up(config.model.batch_size,model)
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
 sent_samples=0;source_samples=0;sample_sequences={};video_sequences={};alignment=[];stale_drops={};drainers=[]
 ended_fragments=set();committed_fragments=set()
 phrases=['今天的測試會先確認聲音是否連續。','接著比較嘴型推理造成的等待。','最後記錄整段語音的播放時間。']
 active_started=asyncio.Event();started_at=None
 expected_samples=int(args.seconds*16000)//320*320
 def match(key):
  if key in sample_sequences and key in video_sequences:
   alignment.append(abs(sample_sequences[key]-video_sequences[key]))
 def on_audio(event,active):
  nonlocal sent_samples
  if event and event.get('turn_id')=='probe':
   key=event.get('media_sequence');sample_sequences[key]=time.monotonic();match(key)
   send_audio_times.append(time.monotonic());sent_samples+=320
   if active:
    active_started.set();committed_fragments.add(event.get('fragment_sequence'))
   if event.get('fragment_end'):
    ended_fragments.add(event.get('fragment_sequence'))
    if not args.speech or event.get('fragment_sequence')==len(phrases)-1:completed.set()
 def on_drop(stage,reason):
  key=stage+':'+reason;stale_drops[key]=stale_drops.get(key,0)+1
 class Player(HumanPlayer):
  def notify_media_timing(self,kind,seconds,event=None):
   super().notify_media_timing(kind,seconds,event)
   if kind=='video' and event and event.get('turn_id')=='probe':
    key=event.get('media_sequence');video_sequences[key]=time.monotonic();match(key)
 player=Player(avatar,on_audio_frame=on_audio,on_stale_drop=on_drop)
 avatar.configure_media_fence(media_guard=lambda *_:not cancelled.is_set(),on_stale_drop=on_drop,
   fragment_playback_committed=lambda e:e.get('fragment_sequence') in committed_fragments,
   fragment_playback_ended=lambda e:e.get('fragment_sequence') in ended_fragments)
 original_put=avatar.put_audio_frame
 def counted_put(chunk,event):
  nonlocal source_samples
  accepted=original_put(chunk,event)
  if accepted:source_samples+=len(chunk)
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
 def feed():
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
 producer=asyncio.create_task(asyncio.to_thread(feed))
 try:
  await asyncio.wait_for(completed.wait(),90 if args.speech else args.seconds*5+8)
  await asyncio.sleep(.3)
 except asyncio.TimeoutError:pass
 cancelled.set()
 report={'height_limit':args.height,'independent_audio':args.independent,'engine':bool(args.engine),
         'speech':args.speech,'legacy_tts_loop':args.legacy_tts_loop,
         'expected_pcm_seconds':source_samples/16000 if args.speech else expected_samples/16000,'sent_pcm_seconds':sent_samples/16000,
         'completion':completed.is_set(),'first_audio_seconds':round(send_audio_times[0]-started_at,4) if send_audio_times else None,
         'active_playback_wall_seconds':round(send_audio_times[-1]-send_audio_times[0]+.02,4) if send_audio_times else None,
         'audio_release_max_gap_ms':round(max(np.diff(send_audio_times))*1000,2) if len(send_audio_times)>1 else None,
         'received_audio_max_gap_ms':round(max(np.diff(received_audio_times))*1000,2) if len(received_audio_times)>1 else None,
         'received_video_frames':len(received_video_times),'av_matched_samples':len(alignment),
         'av_wall_offset_p95_ms':round(float(np.percentile(alignment,95))*1000,2) if alignment else None,
         'stale_drops':stale_drops,'vae_failed':getattr(model[0],'_failed',False)}
 report['audio_continuity_pass']=bool(report['completion'] and abs(report['expected_pcm_seconds']-report['sent_pcm_seconds'])<.001 and report['audio_release_max_gap_ms'] is not None and report['audio_release_max_gap_ms']<60 and (args.speech or (report['received_audio_max_gap_ms'] is not None and report['received_audio_max_gap_ms']<100)))
 if args.speech:report['receiver_gap_note']='Active-voice gaps include natural pauses; continuity gate uses tagged PCM and completeness.'
 report['av_gate_pass']=bool(len(alignment)>=5 and report['av_wall_offset_p95_ms']<=80)
 Path(args.output).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
 # Invalidate pending generations before stopping the render and TTS threads.
 avatar.stop_audio_output();avatar.flush_talk()
 await sender.close();await receiver.close()
 for task in drainers:task.cancel()
 await asyncio.gather(*drainers,return_exceptions=True)
 await asyncio.wait_for(producer,2)
 return report
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--height',type=int,default=0);parser.add_argument('--engine',default='');parser.add_argument('--independent',action='store_true');parser.add_argument('--speech',action='store_true');parser.add_argument('--legacy-tts-loop',action='store_true');parser.add_argument('--seconds',type=float,default=3);parser.add_argument('--output',required=True)
 asyncio.run(run(parser.parse_args()))
