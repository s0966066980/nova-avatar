# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Offline real x264 timing. No production encoder mutation."""
import av,cv2,fractions,json,time
from pathlib import Path
import numpy as np
# Real avatar source, rather than an unrealistically cheap uniform image.
paths=list(Path('data/avatars/musetalk_1').rglob('*.png'))
if not paths:paths=list(Path('data/avatars/musetalk_1').rglob('*.jpg'))
assert paths,'Avatar source frame not found'
image=cv2.imread(str(paths[0]));assert image is not None
rows=[]
for height in (1280,1920):
 frame=cv2.resize(image,(height*9//16,height))
 for preset in (None,'veryfast','ultrafast'):
  c=av.CodecContext.create('libx264','w');c.width=frame.shape[1];c.height=frame.shape[0];c.bit_rate=2000000;c.pix_fmt='yuv420p';c.framerate=fractions.Fraction(30);c.time_base=fractions.Fraction(1,30);c.profile='Baseline';c.options={'level':'31','tune':'zerolatency'}
  if preset:c.options['preset']=preset
  timings=[];sizes=[]
  for i in range(24):
   f=av.VideoFrame.from_ndarray(frame,format='bgr24');f.pts=i;f.time_base=fractions.Fraction(1,25)
   t=time.perf_counter();packets=list(c.encode(f));timings.append((time.perf_counter()-t)*1000);sizes.append(sum(p.size for p in packets))
  rows.append({'height':height,'preset':preset or 'default','median_ms':float(np.median(timings[2:])),'p95_ms':float(np.percentile(timings[2:],95)),'bytes':sum(sizes)})
print(json.dumps(rows,indent=2));Path('.scratch/lfm-resolution/encoder-timing.json').write_text(json.dumps(rows,indent=2)+'\n')
