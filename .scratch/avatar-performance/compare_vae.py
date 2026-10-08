# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
import json,time,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import numpy as np, torch
from src.avatars.musetalk.avatar import load_model
from src.avatars.musetalk.vae_acceleration import TensorRTVAEDecoder
vae,unet,pe,step,audio=load_model()
optimized=TensorRTVAEDecoder(vae,'.scratch/avatar-performance/vae.engine')
source=torch.load('data/avatars/musetalk_1/latents.pt',weights_only=False)[:8]
feature=audio.audio2feat(np.sin(np.arange(16000,dtype=np.float32)*0.06)*0.1)
features=np.stack(audio.feature2chunks(feature,25,8))
report=[]
with torch.no_grad():
 for n in [4,8]:
  z=torch.cat(source[:n]).to(device='cuda',dtype=torch.float16)
  f=pe(torch.from_numpy(features[:n]).to(device='cuda',dtype=torch.float16))
  unet_times=[]
  for i in range(4):
   torch.cuda.synchronize();t=time.perf_counter()
   predicted=unet.model(z,step,encoder_hidden_states=f).sample
   torch.cuda.synchronize()
   if i:unet_times.append((time.perf_counter()-t)*1000)
  unet_ms=float(np.median(unet_times))
  times={};images={}
  for name,decoder in [('pytorch',vae),('tensorrt',optimized)]:
   vals=[]
   for i in range(4):
    torch.cuda.synchronize();t=time.perf_counter();out=decoder.decode_latents(predicted);torch.cuda.synchronize()
    if i:vals.append((time.perf_counter()-t)*1000)
   times[name]=round(float(np.median(vals)),3);images[name]=out.astype(np.float32)
  diff=images['pytorch']-images['tensorrt'];mse=float(np.mean(diff**2));psnr=99.0 if not mse else float(10*np.log10(255**2/mse))
  r={'batch':n,'unet_ms':round(unet_ms,3),'vae_ms':times,'vae_speedup':round(times['pytorch']/times['tensorrt'],3),'psnr_db':round(psnr,3),'mae_pixels':round(float(np.mean(np.abs(diff))),3),'native_failed':optimized._failed,'quality_pass':psnr>=35 and not optimized._failed}
  report.append(r); print(json.dumps(r),flush=True)
Path('.scratch/avatar-performance/vae-comparison.json').write_text(json.dumps(report,indent=2)+'\n')
assert all(r['quality_pass'] for r in report), 'VAE numerical quality gate failed'
