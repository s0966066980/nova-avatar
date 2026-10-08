# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import sys,json
sys.path.insert(0,str(Path.cwd()))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import numpy as np
import torch
from kernel_probe import timed
from src.avatars.musetalk.avatar import load_model
from src.avatars.musetalk.inference_optimization import TensorRTUNet,TinyVAEDecoder
from src.avatars.musetalk.vae_acceleration import TensorRTVAEDecoder

@torch.inference_mode()
def main():
    vae,unet,pe,step,audio=load_model()
    optimized=TensorRTUNet(unet.model,'.scratch/realtime-avatar/unet.engine')
    tiny=TinyVAEDecoder(vae,'.local/jetson/taesd')
    tuned=TensorRTVAEDecoder(vae,'.scratch/realtime-avatar/vae-tuned.engine')
    source=torch.load('data/avatars/musetalk_1/latents.pt',weights_only=False)[:8]
    with np.load('.scratch/fixed-reply-diagnosis/fixed-reply.npz',allow_pickle=False) as fixture:
        feature,feat_ms=timed(lambda:audio.audio2feat(fixture['pcm'][:16000]))
    f=pe(torch.from_numpy(np.stack(audio.feature2chunks(feature,25,8))).to('cuda',torch.float16))
    z=torch.cat(source).to('cuda',torch.float16)
    report=[]
    for n in (8,4,1):
        baseline,pt_ms=timed(lambda:unet.model(z[:n],step,encoder_hidden_states=f[:n]).sample)
        predicted,trt_ms=timed(lambda:optimized(z[:n],step,encoder_hidden_states=f[:n]).sample)
        reference,_=timed(lambda:vae.decode_latents(baseline),1)
        image,_=timed(lambda:vae.decode_latents(predicted),1)
        diff=reference.astype(np.float32)-image.astype(np.float32)
        mse=float(np.mean(diff**2));psnr=99. if mse==0 else float(10*np.log10(255**2/mse))
        _,tiny_ms=timed(lambda:tiny.decode_latents(predicted))
        _,tuned_ms=timed(lambda:tuned.decode_latents(predicted))
        row={'batch':n,'unet_pytorch_ms':pt_ms,'unet_tensorrt_ms':trt_ms,'tiny_vae_ms':tiny_ms,'full_vae_ms':tuned_ms,
             'feature_ms':feat_ms,'unet_image_psnr_db':psnr,'latent_mae':float((predicted-baseline).abs().mean()),
             'unet_failed':optimized._failed,'tiny_failed':tiny._failed,'vae_failed':tuned._failed,'quality_pass':psnr>=35}
        print(json.dumps(row),flush=True);report.append(row)
    Path('.scratch/realtime-avatar/unet-comparison.json').write_text(json.dumps(report,indent=2)+'\n')
    assert all(r['quality_pass'] and not any(r[k] for k in ('unet_failed','tiny_failed','vae_failed')) for r in report)

if __name__=='__main__':main()
