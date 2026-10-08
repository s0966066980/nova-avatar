# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
import torch
from diffusers import AutoencoderTiny

class Decoder(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.tiny=AutoencoderTiny.from_pretrained('.local/jetson/taesd',local_files_only=True,
            torch_dtype=torch.float16).to('cuda').eval()
    def forward(self,latents):return self.tiny.decode(latents,return_dict=False)[0]

with torch.inference_mode():
    model=Decoder()
    torch.onnx.export(model,torch.zeros(1,4,32,32,device='cuda',dtype=torch.float16),
        '.scratch/realtime-avatar/tiny.onnx',input_names=['latents'],output_names=['decoded'],
        dynamic_axes={'latents':{0:'batch'},'decoded':{0:'batch'}},opset_version=17,dynamo=False)
print('Tiny decoder export complete',flush=True)
