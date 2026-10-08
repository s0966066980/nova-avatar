# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
import sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import torch
from src.avatars.musetalk.avatar import load_model
print('Loading VAE',flush=True)
vae,*_=load_model()
class Decoder(torch.nn.Module):
 def __init__(self,vae):
  super().__init__();self.vae=vae.vae;self.scale=vae.scaling_factor
 def forward(self,latents):
  return self.vae.decode(latents/self.scale,return_dict=False)[0]
module=Decoder(vae).eval()
x=torch.ones(8,4,32,32,device='cuda',dtype=torch.float16)
print('Exporting dynamic batch decoder',flush=True)
torch.onnx.export(module,x,'.scratch/avatar-performance/vae.onnx',input_names=['latents'],output_names=['decoded'],dynamic_axes={'latents':{0:'batch'},'decoded':{0:'batch'}},opset_version=17,dynamo=False)
print('Export complete',flush=True)
