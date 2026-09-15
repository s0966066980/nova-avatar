# Derived from Kedreamix/Linly-Talker-Stream.
# Copyright [Linly-talker-stream@kedreamix].
# Licensed under the Apache License, Version 2.0.
# Contains code derived from the Wav2Lip open-source project.
# Upstream non-commercial usage restrictions apply.
#
# Modified by HongXian0903 for integration with Nova Avatar, 2026.
# See THIRD_PARTY_NOTICES.md.
# Based on LiveTalking (C) 2024 LiveTalking@lipku https://github.com/lipku/LiveTalking (Apache-2.0).

"""Wav2Lip 音訊流處理器 - 提取 Mel 頻譜特徵"""
import time
import torch
import numpy as np

import queue
from queue import Queue

from src.avatars.audio_stream_handler import BaseAudioStreamHandler
from src.avatars.wav2lip import audio


class LipAudioStreamHandler(BaseAudioStreamHandler):
    """Mel 頻譜特徵提取器
    
    用於 Wav2Lip Avatar 模型，提取 Mel 頻譜特徵用於唇形同步。
    """

    def run_step(self):
        """執行一步音訊特徵提取"""
        ############################################## extract audio feature ##############################################
        # get a frame of audio
        for _ in range(self.batch_size * 2):
            frame, type, eventpoint = self.get_audio_frame()
            self.frames.append(frame)
            # put to output
            self.output_queue.put((frame, type, eventpoint))
        # context not enough, do not run network.
        if len(self.frames) <= self.stride_left_size + self.stride_right_size:
            return
        
        inputs = np.concatenate(self.frames)  # [N * chunk]
        mel = audio.melspectrogram(inputs)
        #print(mel.shape[0],mel.shape,len(mel[0]),len(self.frames))
        # cut off stride
        left = max(0, self.stride_left_size * 80 / 50)
        right = min(len(mel[0]), len(mel[0]) - self.stride_right_size * 80 / 50)
        mel_idx_multiplier = 80. * 2 / self.fps 
        mel_step_size = 16
        i = 0
        mel_chunks = []
        while i < (len(self.frames) - self.stride_left_size - self.stride_right_size) / 2:
            start_idx = int(left + i * mel_idx_multiplier)
            #print(start_idx)
            if start_idx + mel_step_size > len(mel[0]):
                mel_chunks.append(mel[:, len(mel[0]) - mel_step_size:])
            else:
                mel_chunks.append(mel[:, start_idx : start_idx + mel_step_size])
            i += 1
        self.feat_queue.put(mel_chunks)
        
        # discard the old part to save memory
        self.frames = self.frames[-(self.stride_left_size + self.stride_right_size):]
