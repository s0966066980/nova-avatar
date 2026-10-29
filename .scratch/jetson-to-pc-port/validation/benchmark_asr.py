# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

import asyncio, json, time, statistics, gc, resource
import sys
from pathlib import Path
import torch
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from src.config.schema import Config
from src.tts.engines.edge import _edge_communicate
from src.tts import edge_endpoint
from src.asr.engines.whisper import WhisperASR
root=ROOT/'.scratch/jetson-to-pc-port/validation'
audio=root/'asr-audio';audio.mkdir(exist_ok=True)
rows=[('zh-TW-HsiaoChenNeural','請問今天臺北市的天氣如何？'),('zh-TW-HsiaoChenNeural','請幫我整理這份文件的三個重點。'),('en-US-JennyNeural','What is the weather in Taipei today?'),('en-US-JennyNeural','Please summarize the three main points of this document.')]
async def prepare():
 for i,(voice,text) in enumerate(rows):
  p=audio/f'{i}.mp3'
  if p.exists():continue
  for attempt in range(2):
   try:
    async def synthesize():
     data=bytearray()
     async for chunk in _edge_communicate(text,voice).stream():
      if chunk['type']=='audio':data.extend(chunk['data'])
     if not data:raise RuntimeError('No speech')
     return data
    p.write_bytes(await asyncio.wait_for(synthesize(),20))
    print('Audio ready',i,flush=True);break
   except Exception as exc:
    edge_endpoint.note_failure(exc)
    if attempt:raise
asyncio.run(prepare())
results={}
for size in ['small','turbo']:
 config=Config();config.asr.type='whisper';config.asr.device='cuda';config.asr.language='auto'
 model=WhisperASR(config,model_size=size)
 begin=time.perf_counter();model.prewarm();cold=time.perf_counter()-begin
 samples=[]
 for repeat in range(2):
  for i,(_,reference) in enumerate(rows):
   begin=time.perf_counter();result=model.transcribe((audio/f'{i}.mp3').read_bytes(),language='auto')
   elapsed=time.perf_counter()-begin
   samples.append({'reference':reference,'recognized':result['text'],'seconds':elapsed})
 results[size]={'cold_prewarm_seconds':cold,'warm_median_seconds':statistics.median(r['seconds'] for r in samples),'peak_rss_mib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,'samples':samples}
 print(size,json.dumps(results[size],ensure_ascii=False),flush=True)
 (root/'asr-benchmark.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
 del model;gc.collect();torch.cuda.empty_cache()
