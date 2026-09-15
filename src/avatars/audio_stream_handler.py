# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""音訊流處理器基類 - 用於音訊特徵提取和緩衝管理"""
import time
import numpy as np

import queue
from queue import Queue
import torch.multiprocessing as mp

from src.avatars.base import BaseAvatar


def _drain_queue(target) -> None:
    mutex = getattr(target, "mutex", None)
    storage = getattr(target, "queue", None)
    if mutex is not None and storage is not None:
        with mutex:
            storage.clear()
            not_full = getattr(target, "not_full", None)
            if not_full is not None:
                not_full.notify_all()
        return
    while True:
        try:
            target.get_nowait()
        except queue.Empty:
            return


class BaseAudioStreamHandler:
    """音訊流處理器基類
    
    負責音訊緩衝管理、音訊幀處理和特徵提取的基礎框架。
    各 Avatar 模型應繼承此類並實現 run_step() 方法。
    """
    def __init__(self, config, parent: BaseAvatar = None):
        self.config = config
        self.parent = parent

        # 20ms per frame (50fps audio)
        self.fps = config.audio.fps
        self.sample_rate = 16000
        self.chunk = self.sample_rate // self.fps
        self.queue = Queue()
        # 渲染側消費的音訊輸出佇列
        self.output_queue = mp.Queue()

        self.batch_size = config.model.batch_size

        self.frames = []
        self.stride_left_size = config.audio.l
        self.stride_right_size = config.audio.r
        #self.context_size = 10
        self.feat_queue = mp.Queue(2)

        #self.warm_up()

    def flush_talk(self):
        _drain_queue(self.queue)
        _drain_queue(self.output_queue)
        _drain_queue(self.feat_queue)
        self.frames.clear()

    def put_audio_frame(self, audio_chunk, datainfo: dict):
        while self._accepts_media(datainfo, "avatar_audio_enqueue"):
            try:
                self.queue.put_nowait((audio_chunk, datainfo))
                return True
            except queue.Full:
                time.sleep(0.01)
        self._record_stale_drop("avatar_audio_enqueue")
        return False

    def _accepts_media(self, eventpoint, stage: str) -> bool:
        if not (isinstance(eventpoint, dict) and eventpoint.get("turn_id")):
            return True
        accepts_media = getattr(self.parent, "accepts_media", None)
        return bool(accepts_media(eventpoint, stage)) if callable(accepts_media) else True

    def _record_stale_drop(self, stage: str) -> None:
        record = getattr(self.parent, "record_stale_drop", None)
        if callable(record):
            record(stage, "stale_generation")

    def get_audio_frame(self):        
        while True:
            try:
                frame, eventpoint = self.queue.get(block=True, timeout=0.01)
                if not self._accepts_media(eventpoint, "avatar_audio_consume"):
                    self._record_stale_drop("avatar_audio_consume")
                    continue
                type = 0
                #print(f'[INFO] get frame {frame.shape}')
                break
            except queue.Empty:
                frame, type = self._idle_audio_frame()
                eventpoint = None
                break

        return frame, type, eventpoint 

    def _idle_audio_frame(self):
        if self.parent and getattr(self.parent, "curr_state", 0) > 1:
            return (
                self.parent.get_audio_stream(self.parent.curr_state),
                self.parent.curr_state,
            )
        return np.zeros(self.chunk, dtype=np.float32), 1

    def get_audio_frames(self, count: int):
        """Read one batch with at most one blocking queue poll.

        MuseTalk consumes many 20 ms frames per inference batch.  Waiting up
        to 10 ms independently for every missing frame adds avoidable startup
        latency, so only the first frame may block; the rest are drained
        non-blockingly and padded with the normal idle frame.
        """
        count = max(0, int(count))
        if count == 0:
            return []
        frames = [self.get_audio_frame()]
        while len(frames) < count:
            try:
                frame, eventpoint = self.queue.get_nowait()
                if not self._accepts_media(eventpoint, "avatar_audio_consume"):
                    self._record_stale_drop("avatar_audio_consume")
                    continue
                frames.append((frame, 0, eventpoint))
            except queue.Empty:
                frame, frame_type = self._idle_audio_frame()
                frames.append((frame, frame_type, None))
        return frames

    def get_audio_out(self): 
        return self.output_queue.get()
    
    def av_offset_frames(self) -> int:
        """把 av_offset_ms 換算成音訊幀數，並夾在不會讓輸出佇列見底的範圍內。"""
        offset_ms = int(getattr(self.config.audio, "av_offset_ms", 0) or 0)
        frames = int(round(offset_ms * self.fps / 1000.0))
        # 正值吃的是 warm_up 推進去的 right stride。留 2 幀不動：把積壓抽到 0
        # 會讓音訊軌在 run_step 之間餓死，而餓死的軌會永久落後真實時間。
        return max(-self.stride_left_size, min(frames, max(0, self.stride_right_size - 2)))

    def warm_up(self):
        offset = self.av_offset_frames()
        primed = []
        for _ in range(self.stride_left_size + self.stride_right_size):
            audio_frame, type, eventpoint = self.get_audio_frame()
            self.frames.append(audio_frame)
            primed.append((audio_frame, type, eventpoint))

        # output_queue 是 FIFO，要讓音訊晚出現就得把靜音墊在最前面
        for _ in range(max(0, -offset)):
            self.output_queue.put((np.zeros(self.chunk, dtype=np.float32), 1, None))

        # 丟掉開頭 stride_left 幀是原本就有的對齊；正的 offset 再多丟幾幀，
        # 等於把整條音軌往前拉，用來補償嘴型領先聲音。
        for item in primed[self.stride_left_size + max(0, offset):]:
            self.output_queue.put(item)

    def run_step(self):
        """執行一步音訊處理，子類需要實現此方法"""
        pass

    def get_next_feat(self, block, timeout):        
        return self.feat_queue.get(block, timeout)
