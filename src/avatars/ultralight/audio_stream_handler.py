# Derived from Kedreamix/Linly-Talker-Stream.
# Copyright [Linly-talker-stream@kedreamix].
# Licensed under the Apache License, Version 2.0.
#
# Modified by HongXian0903, 2026.
# See LICENSE, NOTICE, and THIRD_PARTY_NOTICES.md.
# Based on LiveTalking (C) 2024 LiveTalking@lipku https://github.com/lipku/LiveTalking (Apache-2.0).

"""Ultralight 音訊流處理器 - 使用 Hubert 提取音訊特徵"""
import time
import torch
import numpy as np
from src.avatars.audio_stream_handler import BaseAudioStreamHandler
from src.avatars.ultralight.audio2feature import Audio2Feature


class HubertAudioStreamHandler(BaseAudioStreamHandler):
    """Hubert 音訊特徵提取器
    
    用於 Ultralight Avatar 模型，提取 Hubert 音訊特徵。
    """
    def __init__(self, config, parent, audio_processor: Audio2Feature, audio_feat_length=[8, 8]):
        """
        Args:
            config: 配置物件
            parent: 父物件 (BaseAvatar)
            audio_processor: Audio2Feature 例項
            audio_feat_length: 音訊特徵長度 [before, after]
        """
        super().__init__(config, parent)
        self.audio_processor = audio_processor
        self.audio_feat_length = audio_feat_length

    def run_step(self):
        """執行一步音訊特徵提取"""
        start_time = time.time()
        
        for _ in range(self.batch_size * 2):
            audio_frame, type, eventpoint = self.get_audio_frame()
            self.frames.append(audio_frame)
            self.output_queue.put((audio_frame, type, eventpoint))
        
        if len(self.frames) <= self.stride_left_size + self.stride_right_size:
            return
        
        inputs = np.concatenate(self.frames)  # [N * chunk]

        mel = self.audio_processor.get_hubert_from_16k_speech(inputs)
        mel_chunks = self.audio_processor.feature2chunks(
            feature_array=mel,
            fps=self.fps / 2,
            batch_size=self.batch_size,
            audio_feat_length=self.audio_feat_length,
            start=self.stride_left_size / 2
        )

        self.feat_queue.put(mel_chunks)
        self.frames = self.frames[-(self.stride_left_size + self.stride_right_size):]
        #print(f"Processing audio costs {(time.time() - start_time) * 1000}ms")
