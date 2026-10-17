# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
import asyncio,gc,json,sys,weakref
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
import numpy as np
from src.avatars.musetalk.avatar import MuseTalkAvatar
from src.config.schema import Config

def rss():
 return next(int(s.split()[1])/1024 for s in Path('/proc/self/status').read_text().splitlines() if s.startswith('VmRSS:'))

def data(h,w):
 frame=np.zeros((h,w,3),np.uint8)
 mask=np.ones((64,64),np.uint8)*255
 return [frame]*48,[mask]*48,[(0,0,w,h)]*48,[(0,0,w,h)]*48,[None]*48

async def run():
 c=Config();avatar=SimpleNamespace();a=data(1280,720);b=data(1920,1080);refs=[];samples=[]
 for i in range(12):
  await asyncio.to_thread(MuseTalkAvatar._install_assets,avatar,a if i%2==0 else b,c)
  refs.append(weakref.ref(avatar._avatar_transition))
  samples.append(rss())
  print(json.dumps({'switch':i,'rss_mib':samples[-1],'live_controllers':sum(r() is not None for r in refs)}),flush=True)
 gc.collect()
 print('rss_after_gc_mib',rss())
 assert samples[-1]-samples[1]<512,'repeated role material installation retains over 512 MiB'
asyncio.run(run())
