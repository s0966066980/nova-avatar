# Derived from Kedreamix/Linly-Talker-Stream.
# Copyright [Linly-talker-stream@kedreamix].
# Licensed under the Apache License, Version 2.0.
#
# Modified by HongXian0903, 2026.
# See LICENSE, NOTICE, and THIRD_PARTY_NOTICES.md.
import time
import numpy as np
import torch
import torch.nn.functional as F

import queue
from queue import Queue

from src.avatars.audio_stream_handler import BaseAudioStreamHandler

class TalkingGaussianAudioStreamHandler(BaseAudioStreamHandler):
    def __init__(self, config, parent, audio_processor, audio_model):
        super().__init__(config, parent)

        self.device = "cuda" if torch.cuda.is_available() else ("mps" if (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()) else "cpu")
        if 'esperanto' in self.config.model.ernerf.asr_model:
            self.audio_dim = 44
        elif 'deepspeech' in self.config.model.ernerf.asr_model:
            self.audio_dim = 29
        elif 'hubert' in self.config.model.ernerf.asr_model:
            self.audio_dim = 1024
        else:
            self.audio_dim = 32

        # prepare context cache
        # each segment is (stride_left + ctx + stride_right) * 20ms, latency should be (ctx + stride_right) * 20ms
        self.context_size = config.audio.m
        self.stride_left_size = config.audio.l
        self.stride_right_size = config.audio.r

        # pad left frames
        if self.stride_left_size > 0:
            self.frames.extend([np.zeros(self.chunk, dtype=np.float32)] * self.stride_left_size)

        # processor and model
        self.processor = audio_processor
        self.model = audio_model

        # the extracted features 
        # use a loop queue to efficiently record endless features: [f--t---][-------][-------]
        self.feat_buffer_size = 4
        self.feat_buffer_idx = 0
        self.feat_queue = torch.zeros(self.feat_buffer_size * self.context_size, self.audio_dim, dtype=torch.float32, device=self.device)

        # TODO: hard coded 16 and 8 window size...
        self.front = self.feat_buffer_size * self.context_size - 8 # fake padding
        self.tail = 8
        # attention window...
        self.att_feats = [torch.zeros(self.audio_dim, 16, dtype=torch.float32, device=self.device)] * 4 # 4 zero padding...

        # warm up steps needed: mid + right + window_size + attention_size
        self.warm_up_steps = self.context_size + self.stride_left_size + self.stride_right_size #+ self.stride_left_size   #+ 8 + 2 * 3

    def get_next_feat(self): #get audio embedding to nerf
        # return a [1/8, 16] window, for the next input to nerf side.
        if self.config.model.ernerf.att>0:
            while len(self.att_feats) < 8:
                # [------f+++t-----]
                if self.front < self.tail:
                    feat = self.feat_queue[self.front:self.tail]
                # [++t-----------f+]
                else:
                    feat = torch.cat([self.feat_queue[self.front:], self.feat_queue[:self.tail]], dim=0)

                self.front = (self.front + 2) % self.feat_queue.shape[0]
                self.tail = (self.tail + 2) % self.feat_queue.shape[0]

                # print(self.front, self.tail, feat.shape)

                self.att_feats.append(feat.permute(1, 0))
            
            att_feat = torch.stack(self.att_feats, dim=0) # [8, 44, 16]

            # discard old
            self.att_feats = self.att_feats[1:]
        else:
            # [------f+++t-----]
            if self.front < self.tail:
                feat = self.feat_queue[self.front:self.tail]
            # [++t-----------f+]
            else:
                feat = torch.cat([self.feat_queue[self.front:], self.feat_queue[:self.tail]], dim=0)

            self.front = (self.front + 2) % self.feat_queue.shape[0]
            self.tail = (self.tail + 2) % self.feat_queue.shape[0]

            att_feat = feat.permute(1, 0).unsqueeze(0)


        return att_feat

    def run_step(self):

        # get a frame of audio
        frame,type,eventpoint = self.get_audio_frame()
        self.frames.append(frame)
        # put to output
        self.output_queue.put((frame,type,eventpoint))
        # context not enough, do not run network.
        if len(self.frames) < self.stride_left_size + self.context_size + self.stride_right_size:
            return
        
        inputs = np.concatenate(self.frames) # [N * chunk]

        # discard the old part to save memory
        self.frames = self.frames[-(self.stride_left_size + self.stride_right_size):]

        #print(f'[INFO] frame_to_text... ')
        #t = time.time()
        logits, labels, text = self.__frame_to_text(inputs)
        #print(f'-------wav2vec time:{time.time()-t:.4f}s')
        feats = logits # better lips-sync than labels

        # record the feats efficiently.. (no concat, constant memory)
        start = self.feat_buffer_idx * self.context_size
        end = start + feats.shape[0]
        self.feat_queue[start:end] = feats
        self.feat_buffer_idx = (self.feat_buffer_idx + 1) % self.feat_buffer_size
        
    def __frame_to_text(self, frame):
        # frame: [N * 320], N = (context_size + 2 * stride_size)
        
        inputs = self.processor(frame, sampling_rate=self.sample_rate, return_tensors="pt", padding=True)
        
        with torch.no_grad():
            result = self.model(inputs.input_values.to(self.device))
            if 'hubert' in self.config.model.ernerf.asr_model:
                logits = result.last_hidden_state # [B=1, T=pts//320, hid=1024]
            else:
                logits = result.logits # [1, N - 1, 32]
        
        # cut off stride
        left = max(0, self.stride_left_size)
        right = min(logits.shape[1], logits.shape[1] - self.stride_right_size + 1) # +1 to make sure output is the same length as input.

        logits = logits[:, left:right]

        return logits[0], None,None #predicted_ids[0], transcription # [N,]
    

    def warm_up(self):       
        print(f'[INFO] warm up ASR live model, expected latency = {self.warm_up_steps / self.fps:.6f}s')
        t = time.time()
        for _ in range(self.warm_up_steps):
            self.run_step()
        t = time.time() - t
        print(f'[INFO] warm-up done, actual latency = {t:.6f}s')

    def stop(self):
        """停止音訊處理"""
        pass
