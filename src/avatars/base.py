# Derived from Kedreamix/Linly-Talker-Stream.
# Copyright [Linly-talker-stream@kedreamix].
# Licensed under the Apache License, Version 2.0.
#
# Modified by HongXian0903, 2026.
# See LICENSE and NOTICE for details.
# Based on LiveTalking (C) 2024 LiveTalking@lipku https://github.com/lipku/LiveTalking (Apache-2.0).

import math
import torch
import numpy as np

import subprocess
import os
import time
import cv2
import glob
import resampy
from datetime import datetime

import queue
from queue import Queue
from threading import Thread, Event, RLock
from io import BytesIO
import soundfile as sf

import asyncio
from concurrent.futures import TimeoutError as FutureTimeoutError
from av import AudioFrame, VideoFrame

import av
from fractions import Fraction

from src.tts.factory import create_tts_engine
from src.tts.base import sanitize_speech_text
from src.utils.logging import logger

from tqdm import tqdm


def wait_media_coroutine(coroutine, loop, quit_event) -> bool:
    future = asyncio.run_coroutine_threadsafe(coroutine, loop)
    while not quit_event.is_set():
        try:
            future.result(timeout=0.1)
            return True
        except FutureTimeoutError:
            continue
        except Exception as exc:
            logger.warning("media queue stopped: %s", exc)
            return False
    future.cancel()
    return False


def enqueue_media_frame(track, frame, eventpoint, loop, quit_event) -> bool:
    """Queue one frame from the renderer thread while honoring WebRTC backpressure."""
    enqueue = getattr(track, "enqueue", None)
    coroutine = (
        enqueue(frame, eventpoint)
        if callable(enqueue)
        else track._queue.put((frame, eventpoint))
    )
    return wait_media_coroutine(coroutine, loop, quit_event)


def drain_media_queue(target) -> None:
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


def read_imgs(img_list):
    frames = []
    logger.info('reading images...')
    for img_path in tqdm(img_list):
        frame = cv2.imread(img_path)
        frames.append(frame)
    return frames

def play_audio(quit_event,queue):        
    import pyaudio
    p = pyaudio.PyAudio()
    stream = p.open(
        rate=16000,
        channels=1,
        format=8,
        output=True,
        output_device_index=1,
    )
    stream.start_stream()
    while not quit_event.is_set():
        stream.write(queue.get(block=True))
    stream.close()

class BaseAvatar:
    def __init__(self, config):
        self.config = config
        self.sample_rate = 16000
        # 每個音訊塊對應一幀影片（例如 50fps 音訊 -> 20ms 一個 chunk）
        self.chunk = self.sample_rate // config.audio.fps
        self.sessionid = self.config.sessionid

        # TTS 引擎負責把文本轉成音訊並推送到音訊流
        self.tts = create_tts_engine(config.tts.type, config, self)
        self.speaking = False

        # 錄製相關狀態
        self.recording = False
        self._record_video_pipe = None
        self._record_audio_pipe = None
        self.width = self.height = 0
        self.current_record_file = None  # 當前錄製的檔名

        # 自定義音影片迴圈播放相關
        self.curr_state=0
        self.custom_img_cycle = {}
        self.custom_audio_cycle = {}
        self.custom_audio_index = {}
        self.custom_index = {}
        self.custom_opt = {}
        self._media_guard = None
        self._on_stale_drop = None
        self._on_fragment_queued = None
        self._on_fragment_failed = None
        self._fragment_playback_committed = None
        self._fragment_playback_ended = None
        self._on_tts_onset_preroll_ms = None
        self._on_tts_retry = None
        self._on_stage_end = None
        self._on_llm_chunk = None
        self._direct_audio_track = None
        self._direct_audio_loop = None
        self._direct_audio_quit = Event()
        self._media_sequence_lock = RLock()
        self._media_sequences = {}
        # Optional visual-only seam installed by model-specific avatars.
        self._mouth_continuity = None
        self._avatar_transition = None
        self.__loadcustom()

    def put_msg_txt(self,msg,datainfo:dict={}):
        # 文本訊息交給 TTS 處理
        msg = sanitize_speech_text(msg)
        if not msg:
            return
        eventpoint = dict(datainfo or {})
        if self._on_fragment_queued is not None and eventpoint.get("turn_id"):
            self._on_fragment_queued(msg, eventpoint)
        self.tts.put_msg_txt(msg,eventpoint)
    
    def configure_media_fence(
        self,
        *,
        media_guard,
        on_stale_drop,
        on_fragment_queued=None,
        on_fragment_failed=None,
        fragment_playback_committed=None,
        fragment_playback_ended=None,
        on_tts_onset_preroll_ms=None,
        on_tts_retry=None,
        on_stage_end=None,
        on_llm_chunk=None,
    ):
        """Attach the voice session's generation authority to media boundaries."""
        self._media_guard = media_guard
        self._on_stale_drop = on_stale_drop
        self._on_fragment_queued = on_fragment_queued
        self._on_fragment_failed = on_fragment_failed
        self._fragment_playback_committed = fragment_playback_committed
        self._fragment_playback_ended = fragment_playback_ended
        self._on_tts_onset_preroll_ms = on_tts_onset_preroll_ms
        self._on_tts_retry = on_tts_retry
        self._on_stage_end = on_stage_end
        self._on_llm_chunk = on_llm_chunk
        if not hasattr(self, "_media_sequence_lock"):
            self._media_sequence_lock = RLock()
            self._media_sequences = {}

    def configure_audio_output(self, audio_track, loop) -> None:
        """Attach an optional direct PCM fan-out for low-latency playback.

        TTS producers run independently of avatar inference.  When configured,
        PCM is sent to WebRTC as soon as it is produced while the renderer keeps
        the same frames only for MuseTalk's mouth-pose alignment.
        """
        self._direct_audio_track = audio_track
        self._direct_audio_loop = loop
        self._direct_audio_quit = Event()

    @property
    def direct_audio_enabled(self) -> bool:
        return (
            getattr(self, "_direct_audio_track", None) is not None
            and getattr(self, "_direct_audio_loop", None) is not None
        )

    def _enqueue_direct_audio(self, audio_chunk, eventpoint: dict) -> bool:
        if not self.direct_audio_enabled:
            return True
        frame = np.asarray(audio_chunk, dtype=np.float32)
        pcm = (frame * 32767).astype(np.int16)
        new_frame = AudioFrame(format="s16", layout="mono", samples=pcm.shape[0])
        new_frame.planes[0].update(pcm.tobytes())
        new_frame.sample_rate = 16000
        if eventpoint.get("status") == "start":
            prepare = getattr(self._direct_audio_track, "prepare_speech_start", None)
            if callable(prepare) and not wait_media_coroutine(
                prepare(), self._direct_audio_loop, self._direct_audio_quit
            ):
                return False
        queued = enqueue_media_frame(
            self._direct_audio_track,
            new_frame,
            eventpoint,
            self._direct_audio_loop,
            self._direct_audio_quit,
        )
        if queued:
            self.record_audio_data(pcm)
            if eventpoint.get("turn_id"):
                self.mark_stage_end("webrtc_audio_enqueue")
            if eventpoint.get("fragment_end"):
                # Edge's final PCM may itself be non-silent. Add one tagged
                # silence frame so the playback clock can emit speaking_end
                # and close the turn without waiting for renderer idle output.
                silence = np.zeros(self.chunk, dtype=np.int16)
                silence_frame = AudioFrame(
                    format="s16", layout="mono", samples=silence.shape[0]
                )
                silence_frame.planes[0].update(silence.tobytes())
                silence_frame.sample_rate = 16000
                queued = enqueue_media_frame(
                    self._direct_audio_track,
                    silence_frame,
                    eventpoint,
                    self._direct_audio_loop,
                    self._direct_audio_quit,
                )
        return queued

    def fragment_playback_committed(self, eventpoint: dict) -> bool:
        checker = self._fragment_playback_committed
        if not callable(checker):
            return False
        return bool(checker(eventpoint))

    def fragment_playback_ended(self, eventpoint: dict) -> bool:
        checker = self._fragment_playback_ended
        return bool(checker(eventpoint)) if callable(checker) else True

    def notify_fragment_synthesis_failed(
        self,
        eventpoint: dict,
        reason: str,
    ) -> None:
        callback = self._on_fragment_failed
        if callable(callback):
            callback(dict(eventpoint), str(reason))

    def observe_tts_onset_preroll_ms(self, milliseconds: float) -> None:
        if self._on_tts_onset_preroll_ms is not None:
            self._on_tts_onset_preroll_ms(milliseconds)

    def observe_tts_retry(self, *, after_commit: bool) -> None:
        if self._on_tts_retry is not None:
            self._on_tts_retry(after_commit=after_commit)

    def mark_stage_end(self, stage: str) -> None:
        if self._on_stage_end is not None:
            self._on_stage_end(stage)

    def notify_llm_chunk(self, text: str, eventpoint: dict | None = None) -> None:
        if self._on_llm_chunk is not None:
            self._on_llm_chunk(text, dict(eventpoint or {}))

    def accepts_media(self, eventpoint, stage: str) -> bool:
        if not (isinstance(eventpoint, dict) and eventpoint.get("turn_id")):
            return True
        if self._media_guard is None:
            return True
        return bool(self._media_guard(eventpoint, stage))

    def record_stale_drop(self, stage: str, reason: str) -> None:
        if self._on_stale_drop is not None:
            self._on_stale_drop(stage, reason)

    def put_audio_frame(self,audio_chunk,datainfo:dict={}): #16khz 20ms pcm
        # 直接把音訊塊推給音訊流（用於 WebRTC / 錄製）
        eventpoint = dict(datainfo or {})
        if not self.accepts_media(eventpoint, "avatar_audio_enqueue"):
            self.record_stale_drop("avatar_audio_enqueue", "stale_generation")
            return False
        if (
            eventpoint.get("turn_id")
            and eventpoint.get("generation") is not None
            and eventpoint.get("fragment_sequence") is not None
        ):
            key = (eventpoint["turn_id"], int(eventpoint["generation"]))
            with self._media_sequence_lock:
                sequence = self._media_sequences.get(key, 0)
                self._media_sequences[key] = sequence + 1
            eventpoint["fragment_media_sequence"] = int(
                eventpoint.get("media_sequence", 0)
            )
            eventpoint["media_sequence"] = sequence
        accepted = self.audio_stream.put_audio_frame(audio_chunk,eventpoint)
        if not accepted:
            return False
        return self._enqueue_direct_audio(audio_chunk, eventpoint)

    def put_audio_file(self,filebyte,datainfo:dict={}): 
        # 檔案音訊按 chunk 切片後送入音訊流
        input_stream = BytesIO(filebyte)
        stream = self.__create_bytes_stream(input_stream)
        streamlen = stream.shape[0]
        idx=0
        while streamlen >= self.chunk:  #and self.state==State.RUNNING
            self.put_audio_frame(stream[idx:idx+self.chunk],datainfo)
            streamlen -= self.chunk
            idx += self.chunk
    
    def __create_bytes_stream(self,byte_stream):
        stream, sample_rate = sf.read(byte_stream) # [T*sample_rate,] float64
        logger.info(f'[INFO]put audio stream {sample_rate}: {stream.shape}')
        stream = stream.astype(np.float32)

        if stream.ndim > 1:
            logger.info(f'[WARN] audio has {stream.shape[1]} channels, only use the first.')
            stream = stream[:, 0]
    
        if sample_rate != self.sample_rate and stream.shape[0]>0:
            logger.info(f'[WARN] audio sample rate is {sample_rate}, resampling into {self.sample_rate}.')
            stream = resampy.resample(x=stream, sr_orig=sample_rate, sr_new=self.sample_rate)

        return stream

    def flush_talk(self):
        # 清空 TTS 和音訊流佇列，快速打斷當前發聲
        self.tts.flush_talk()
        self.audio_stream.flush_talk()
        result_queue = getattr(self, "res_frame_queue", None)
        if result_queue is not None:
            drain_media_queue(result_queue)
        with self._media_sequence_lock:
            self._media_sequences.clear()
        mouth_continuity = getattr(self, "_mouth_continuity", None)
        if mouth_continuity is not None:
            mouth_continuity.reset()
        transition = getattr(self, "_avatar_transition", None)
        if transition is not None:
            transition.reset()

    def _compose_mouth_continuity(
        self,
        frame,
        *,
        index: int,
        is_speech: bool,
        eventpoint: dict | None,
    ):
        """Apply the model-owned mouth transition without touching media timing."""
        controller = getattr(self, "_mouth_continuity", None)
        if controller is None:
            return frame
        try:
            return controller.compose(
                frame,
                index=index,
                is_speech=is_speech,
                eventpoint=eventpoint,
            )
        except Exception as exc:
            # A visual enhancement must never stop the audio/video pipeline.
            logger.warning("mouth continuity fallback: %s", exc)
            self._mouth_continuity = None
            return frame

    def _compose_avatar_transition(self, frame, *, index: int, is_speech: bool,
                                   frame_type: int, eventpoint: dict | None):
        controller = getattr(self, "_avatar_transition", None)
        if controller is None:
            return self._compose_mouth_continuity(frame, index=index, is_speech=is_speech, eventpoint=eventpoint)
        try:
            return controller.compose(frame, index=index, is_speech=is_speech, frame_type=frame_type, eventpoint=eventpoint)
        except Exception as exc:
            logger.warning("avatar transition fallback: %s", exc)
            self._avatar_transition = None
            return self._compose_mouth_continuity(frame, index=index, is_speech=is_speech, eventpoint=eventpoint)

    def is_speaking(self)->bool:
        return self.speaking
    
    def __loadcustom(self):
        # 讀取自定義音影片素材（用於特殊動作/表情）
        for item in self.config.customopt:
            logger.info(item)
            input_img_list = glob.glob(os.path.join(item['imgpath'], '*.[jpJP][pnPN]*[gG]'))
            input_img_list = sorted(input_img_list, key=lambda x: int(os.path.splitext(os.path.basename(x))[0]))
            self.custom_img_cycle[item['audiotype']] = read_imgs(input_img_list)
            self.custom_audio_cycle[item['audiotype']], sample_rate = sf.read(item['audiopath'], dtype='float32')
            self.custom_audio_index[item['audiotype']] = 0
            self.custom_index[item['audiotype']] = 0
            self.custom_opt[item['audiotype']] = item

    def init_customindex(self):
        self.curr_state=0
        for key in self.custom_audio_index:
            self.custom_audio_index[key]=0
        for key in self.custom_index:
            self.custom_index[key]=0

    def notify(self,eventpoint):
        if not isinstance(eventpoint, dict):
            return
        if not (
            eventpoint.get("status")
            or eventpoint.get("fragment_start")
            or eventpoint.get("fragment_end")
        ):
            return
        logger.info(
            "media boundary status=%s generation=%s fragment=%s media=%s start=%s end=%s",
            eventpoint.get("status"),
            eventpoint.get("generation"),
            eventpoint.get("fragment_sequence"),
            eventpoint.get("media_sequence"),
            bool(eventpoint.get("fragment_start")),
            bool(eventpoint.get("fragment_end")),
        )

    def mirror_index(self,size, index):
        # 通過映象索引實現正反往返播放
        #size = len(self.coord_list_cycle)
        turn = index // size
        res = index % size
        if turn % 2 == 0:
            return res
        else:
            return size - res - 1 
    
    def get_audio_stream(self,audiotype):
        # 按 chunk 切片返回自定義音訊片段
        idx = self.custom_audio_index[audiotype]
        stream = self.custom_audio_cycle[audiotype][idx:idx+self.chunk]
        self.custom_audio_index[audiotype] += self.chunk
        if self.custom_audio_index[audiotype]>=self.custom_audio_cycle[audiotype].shape[0]:
            self.curr_state = 1  #當前影片不迴圈播放，切換到靜音狀態
        return stream
    
    def set_custom_state(self,audiotype, reinit=True):
        print('set_custom_state:',audiotype)
        if self.custom_audio_index.get(audiotype) is None:
            return
        self.curr_state = audiotype
        if reinit:
            self.custom_audio_index[audiotype] = 0
            self.custom_index[audiotype] = 0

    def process_frames(self,quit_event,loop=None,audio_track=None,video_track=None):
        logger.info(f'[幀處理] process_frames 執行緒啟動, sessionid={self.config.sessionid}')
        while not quit_event.is_set():
            try:
                res_frame,idx,audio_frames = self.res_frame_queue.get(block=True, timeout=1)
            except queue.Empty:
                continue
            turn_events = [
                eventpoint
                for _frame, _frame_type, eventpoint in audio_frames
                if isinstance(eventpoint, dict) and eventpoint.get("turn_id")
            ]
            if turn_events and not all(
                self.accepts_media(eventpoint, "musetalk_result_consume")
                for eventpoint in turn_events
            ):
                self.record_stale_drop(
                    "musetalk_result_consume",
                    "stale_generation",
                )
                continue
            video_eventpoint = dict(turn_events[0]) if turn_events else None

            # Audio is the user-visible clock. Enqueue it before the potentially
            # expensive paste-back/encode path so the first PCM frame is not
            # blocked behind video compositing.
            speech_starts = any(
                isinstance(audio_frame[2], dict)
                and audio_frame[2].get("status") == "start"
                for audio_frame in audio_frames
            )
            prepare_speech_start = getattr(
                audio_track, "prepare_speech_start", None
            )
            if speech_starts and callable(prepare_speech_start):
                logger.info(
                    "[AVSync] speech start queued audio=%d video=%d",
                    getattr(audio_track, "_queue", None).qsize()
                    if getattr(audio_track, "_queue", None) is not None
                    else -1,
                    getattr(video_track, "_queue", None).qsize()
                    if getattr(video_track, "_queue", None) is not None
                    else -1,
                )
                if not wait_media_coroutine(
                    prepare_speech_start(), loop, quit_event
                ):
                    break
            direct_batch_contains_speech = any(
                frame_type == 0 for _frame, frame_type, _eventpoint in audio_frames
            )
            if not self.direct_audio_enabled or not direct_batch_contains_speech:
                audio_enqueue_failed = False
                for audio_frame in audio_frames:
                    frame, type, eventpoint = audio_frame
                    frame = (frame * 32767).astype(np.int16)
                    new_audio_frame = AudioFrame(
                        format="s16", layout="mono", samples=frame.shape[0]
                    )
                    new_audio_frame.planes[0].update(frame.tobytes())
                    new_audio_frame.sample_rate = 16000
                    if not enqueue_media_frame(
                        audio_track, new_audio_frame, eventpoint, loop, quit_event
                    ):
                        audio_enqueue_failed = True
                        break
                    self.record_audio_data(frame)
                    if type == 0:
                        self.mark_stage_end("webrtc_audio_enqueue")
                if audio_enqueue_failed:
                    break
            
            if audio_frames[0][1]!=0 and audio_frames[1][1]!=0:  # 靜音時使用靜態幀或自定義影片
                self.speaking = False
                audiotype = audio_frames[0][1]
                if self.custom_index.get(audiotype) is not None: #有自定義影片
                    mirindex = self.mirror_index(len(self.custom_img_cycle[audiotype]),self.custom_index[audiotype])
                    target_frame = self.custom_img_cycle[audiotype][mirindex]
                    self.custom_index[audiotype] += 1
                else:
                    target_frame = self.frame_list_cycle[idx]
                
                combine_frame = target_frame
            else:
                self.speaking = True
                try:
                    current_frame = self.paste_back_frame(res_frame,idx)
                    self.mark_stage_end("avatar_pasteback_done")
                except Exception as e:
                    logger.warning(f"paste_back_frame error: {e}")
                    continue
                combine_frame = current_frame

            # Do not advance visual transition state for a frame that cannot
            # be queued behind direct-audio playback yet.
            if self.direct_audio_enabled:
                audio_queue = getattr(audio_track, "_queue", None)
                if audio_queue is not None and audio_queue.qsize() == 0:
                    continue
            combine_frame = self._compose_avatar_transition(
                combine_frame,
                index=idx,
                is_speech=self.speaking,
                frame_type=0 if self.speaking else audiotype,
                eventpoint=video_eventpoint,
            )
            cv2.putText(combine_frame, "Nova Avatar", (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (128,128,128), 1)
           
            image = combine_frame
            new_frame = VideoFrame.from_ndarray(image, format="bgr24")
            # 子執行緒推送到 WebRTC 佇列
            if not enqueue_media_frame(
                video_track, new_frame, video_eventpoint, loop, quit_event
            ):
                break
            if video_eventpoint is not None:
                self.mark_stage_end("webrtc_video_enqueue")
            self.record_video_data(combine_frame)
        logger.info('basereal process_frames thread stop') 


    def start_recording(self):
        """開始錄製影片"""
        logger.info(f'[錄製] start_recording 被呼叫, sessionid={self.config.sessionid}')
        logger.info(f'[錄製] 當前 recording 狀態: {self.recording}')
        logger.info(f'[錄製] 當前影片尺寸: width={self.width}, height={self.height}')
        
        if self.recording:
            logger.warning(f'[錄製] 已經在錄製中，忽略本次呼叫')
            return

        # 等到首幀拿到真實尺寸後再啟動 ffmpeg
        self.recording = True
        if self.width == 0 or self.height == 0:
            logger.info(f'[錄製] 影片尺寸未初始化，將在第一幀資料到達時啟動 ffmpeg 程式')
            return
        
        # 如果尺寸已知，立即啟動 ffmpeg 程式
        self._init_recording_pipes()
    
    def _init_recording_pipes(self):
        """初始化錄製管道（需要在 width/height 已知後呼叫）"""
        if self._record_video_pipe is not None:
            return  # 已經初始化過了
        
        logger.info(f'[錄製] 初始化 ffmpeg 程式，影片尺寸: {self.width}x{self.height}')
        
        command = ['ffmpeg',
                    '-y', '-an',
                    '-f', 'rawvideo',
                    '-vcodec','rawvideo',
                    '-pix_fmt', 'bgr24', #畫素格式
                    '-s', "{}x{}".format(self.width, self.height),
                    '-r', str(25),
                    '-i', '-',
                    '-pix_fmt', 'yuv420p', 
                    '-vcodec', "h264",
                    #'-f' , 'flv',                  
                    f'temp{self.config.sessionid}.mp4']
        logger.info(f'[錄製] 啟動影片錄製程式: {" ".join(command)}')
        self._record_video_pipe = subprocess.Popen(command, shell=False, stdin=subprocess.PIPE)
        logger.info(f'[錄製] 影片錄製程式 PID: {self._record_video_pipe.pid}')

        acommand = ['ffmpeg',
                    '-y', '-vn',
                    '-f', 's16le',
                    #'-acodec','pcm_s16le',
                    '-ac', '1',
                    '-ar', '16000',
                    '-i', '-',
                    '-acodec', 'aac',
                    #'-f' , 'wav',                  
                    f'temp{self.config.sessionid}.aac']
        logger.info(f'[錄製] 啟動音訊錄製程式: {" ".join(acommand)}')
        self._record_audio_pipe = subprocess.Popen(acommand, shell=False, stdin=subprocess.PIPE)
        logger.info(f'[錄製] 音訊錄製程式 PID: {self._record_audio_pipe.pid}')
        logger.info(f'[錄製] ffmpeg 程式初始化完成')
    
    def record_video_data(self,image):
        # 首幀到來時寫入真實尺寸
        if self.width == 0:
            print("image.shape:",image.shape)
            self.height,self.width,_ = image.shape
        if self.recording:
            self._record_video_pipe.stdin.write(image.tostring())

    def record_audio_data(self,frame):
        if self.recording:
            self._record_audio_pipe.stdin.write(frame.tostring())
    
    def stop_recording(self):
        """停止錄製影片"""
        logger.info(f'[錄製] stop_recording 被呼叫, sessionid={self.config.sessionid}')
        logger.info(f'[錄製] 當前 recording 狀態: {self.recording}')
        
        if not self.recording:
            logger.warning(f'[錄製] 當前未在錄製狀態，忽略停止請求')
            return
        
        self.recording = False
        
        # 檢查是否已經初始化了管道
        if self._record_video_pipe is None or self._record_audio_pipe is None:
            logger.warning(f'[錄製] ffmpeg 程式未初始化（可能尚未收到第一幀資料），無法停止錄製')
            return
        
        logger.info(f'[錄製] 開始關閉錄製程式...')
        
        try:
            self._record_video_pipe.stdin.close()
            logger.info(f'[錄製] 影片管道已關閉，等待程式結束...')
            self._record_video_pipe.wait()
            logger.info(f'[錄製] 影片錄製程式已結束')
        except Exception as e:
            logger.error(f'[錄製] 關閉影片錄製程式失敗: {e}')
        
        try:
            self._record_audio_pipe.stdin.close()
            logger.info(f'[錄製] 音訊管道已關閉，等待程式結束...')
            self._record_audio_pipe.wait()
            logger.info(f'[錄製] 音訊錄製程式已結束')
        except Exception as e:
            logger.error(f'[錄製] 關閉音訊錄製程式失敗: {e}')
        
        # 重置管道
        self._record_video_pipe = None
        self._record_audio_pipe = None
        
        # 生成唯一檔名（帶時間戳）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        records_dir = 'data/records'
        os.makedirs(records_dir, exist_ok=True)
        
        video_file = f'temp{self.config.sessionid}.mp4'
        audio_file = f'temp{self.config.sessionid}.aac'
        output_file = f'{records_dir}/record_{timestamp}_session{self.config.sessionid}.mp4'
        
        logger.info(f'[錄製] 檢查臨時檔案:')
        logger.info(f'[錄製]   影片檔案: {video_file}, 存在: {os.path.exists(video_file)}')
        if os.path.exists(video_file):
            logger.info(f'[錄製]   影片檔案大小: {os.path.getsize(video_file)} bytes')
        logger.info(f'[錄製]   音訊檔案: {audio_file}, 存在: {os.path.exists(audio_file)}')
        if os.path.exists(audio_file):
            logger.info(f'[錄製]   音訊檔案大小: {os.path.getsize(audio_file)} bytes')
        
        cmd_combine_audio = f"ffmpeg -y -i {audio_file} -i {video_file} -c:v copy -c:a copy {output_file}"
        logger.info(f'[錄製] 合併音影片命令: {cmd_combine_audio}')
        result = os.system(cmd_combine_audio)
        logger.info(f'[錄製] 合併命令返回值: {result}')
        
        if os.path.exists(output_file):
            logger.info(f'[錄製] ✓ 錄製完成! 輸出檔案: {output_file}, 大小: {os.path.getsize(output_file)} bytes')
            self.current_record_file = output_file  # 儲存檔案路徑
        else:
            logger.error(f'[錄製] ✗ 輸出檔案未生成: {output_file}')
            self.current_record_file = None
        
        # 清理臨時檔案
        try:
            if os.path.exists(video_file):
                os.remove(video_file)
                logger.info(f'[錄製] 已刪除臨時影片檔案: {video_file}')
            if os.path.exists(audio_file):
                os.remove(audio_file)
                logger.info(f'[錄製] 已刪除臨時音訊檔案: {audio_file}')
        except Exception as e:
            logger.warning(f'[錄製] 清理臨時檔案失敗: {e}')
