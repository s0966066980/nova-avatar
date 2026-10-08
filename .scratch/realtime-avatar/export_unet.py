# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Export the existing MuseTalk UNet with its single zero diffusion step."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path.cwd()))
import torch
from src.avatars.musetalk.avatar import load_model


class Predictor(torch.nn.Module):
    def __init__(self, unet):
        super().__init__()
        self.unet = unet.model.eval()

    def forward(self, sample, encoder_hidden_states):
        return self.unet(sample, 0, encoder_hidden_states=encoder_hidden_states, return_dict=False)[0]


@torch.inference_mode()
def main():
    _, unet, *_ = load_model()
    module = Predictor(unet)
    print('Exporting current FP16 UNet, batch profile 1-8',flush=True)
    sample = torch.zeros(1,8,32,32,device='cuda',dtype=torch.float16)
    features = torch.zeros(1,50,384,device='cuda',dtype=torch.float16)
    torch.onnx.export(module,(sample,features),'.scratch/realtime-avatar/unet.onnx',
        input_names=['sample','encoder_hidden_states'],output_names=['latent'],
        dynamic_axes={'sample':{0:'batch'},'encoder_hidden_states':{0:'batch'},'latent':{0:'batch'}},
        opset_version=17,dynamo=False)
    print('UNet export complete',flush=True)


if __name__=='__main__':
    main()
