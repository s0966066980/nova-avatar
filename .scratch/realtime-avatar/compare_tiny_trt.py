# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import sys,json
sys.path.insert(0,str(Path.cwd()))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import numpy as np,torch
from kernel_probe import timed
from src.avatars.musetalk.avatar import load_model
from src.avatars.musetalk.inference_optimization import TinyVAEDecoder
from src.avatars.musetalk.vae_acceleration import TensorRTVAEDecoder
@torch.inference_mode()
def main():
    vae,unet,pe,step,audio=load_model()
    tiny=TinyVAEDecoder(vae,'.local/jetson/taesd')
    optimized=TensorRTVAEDecoder(tiny,'.scratch/realtime-avatar/tiny-fp32.engine')
    z=torch.randn(8,4,32,32,device='cuda',dtype=torch.float16)*.2
    report=[]
    for n in (8,4,1):
        reference,pt=timed(lambda:tiny.decode_latents(z[:n]))
        image,trt=timed(lambda:optimized.decode_latents(z[:n]))
        diff=reference.astype(np.float32)-image.astype(np.float32)
        mse=float(np.mean(diff**2))
        row=dict(batch=n,pytorch_ms=pt,tensorrt_ms=trt,psnr=99. if mse==0 else float(10*np.log10(255**2/mse)),failed=optimized._failed)
        report.append(row);print(json.dumps(row),flush=True)
    Path('.scratch/realtime-avatar/tiny-trt-comparison.json').write_text(json.dumps(report,indent=2)+'\n')
    assert all(not r['failed'] and r['psnr']>=35 for r in report)
main()
