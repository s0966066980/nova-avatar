import asyncio
from fractions import Fraction
import gc
import json
import resource
import time

import av
import numpy as np
from aiortc.codecs.h264 import H264Encoder
from aiortc.codecs.opus import OpusEncoder

resource.setrlimit(resource.RLIMIT_CORE,(0,0))

async def session(index,round_index):
    video=H264Encoder()
    audio=OpusEncoder()
    count=0
    for n in range(100):
        vf=av.VideoFrame.from_ndarray(np.zeros((32,64,3),dtype=np.uint8),format='bgr24')
        vf.pts=n*3600
        vf.time_base=Fraction(1,90000)
        af=av.AudioFrame(format='s16',layout='mono',samples=320)
        af.planes[0].update(bytes(640))
        af.sample_rate=16000
        af.pts=n*320
        af.time_base=Fraction(1,16000)
        results=await asyncio.gather(asyncio.to_thread(video.encode,vf),asyncio.to_thread(audio.encode,af))
        count+=sum(len(item[0]) for item in results)
    return count

async def main():
    started=time.monotonic()
    print(json.dumps({'av':av.__version__,'test':'two independent 64x32 H264 and mono Opus encoders','rounds':20,'frames_per_session':100}),flush=True)
    for r in range(20):
        counts=await asyncio.gather(session(0,r),session(1,r))
        gc.collect()
        print(json.dumps({'round':r,'packets':counts,'seconds':round(time.monotonic()-started,3)}),flush=True)

asyncio.run(main())
