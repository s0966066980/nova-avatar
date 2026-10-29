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
import shutil
import tempfile
import time
import cv2
import glob
import resampy
from datetime import datetime
from pathlib import Path

import queue
from queue import Queue
from threading import Thread, Event, RLock
from io import BytesIO
import soundfile as sf

import asyncio
from contextlib import nullcontext
from concurrent.futures import TimeoutError as FutureTimeoutError
from av import AudioFrame, VideoFrame

import av
from fractions import Fraction

from src.tts.factory import create_tts_engine
from src.tts.base import sanitize_speech_text
from src.utils.logging import logger
from src.avatars.video_output import limit_video_height
from src.vad.audio import AudioTooLongError

from tqdm import tqdm

# Audio files sent to /humanaudio are decoded only up to this length.
MAX_AUDIO_FILE_SECONDS = 300.0
# Finished recordings; /download serves files from here.
RECORDS_DIR = Path('data/records')
RECORD_STOP_TIMEOUT_SECONDS = 30.0
RECORD_MERGE_TIMEOUT_SECONDS = 120.0


async def _run_ffmpeg(*arguments: str, timeout: float = RECORD_MERGE_TIMEOUT_SECONDS) -> int:
    """Run ffmpeg with an argv list (no shell) and wait without blocking the loop."""
    process = await asyncio.create_subprocess_exec(
        'ffmpeg', *arguments,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        return await asyncio.wait_for(process.wait(), timeout)
    except BaseException:
        # Timed out, or the request was cancelled: do not leave ffmpeg running.
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise


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


def put_until_quit(target, item, quit_event, poll: float = 0.1) -> bool:
    """Bounded put so a producer thread can stop once its consumer is gone."""
    while not quit_event.is_set():
        try:
            target.put(item, block=True, timeout=poll)
            return True
        except queue.Full:
            continue
    return False


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
        from src.avatars.catalog import avatar_uses_green_screen

        self._green_screen = (
            config.model.type == "musetalk"
            and avatar_uses_green_screen(config.model.avatar_id)
        )
        self.sample_rate = 16000
        # 每個音訊塊對應一幀影片（例如 50fps 音訊 -> 20ms 一個 chunk）
        self.chunk = self.sample_rate // config.audio.fps
        self.sessionid = self.config.sessionid

        # TTS 引擎負責把文本轉成音訊並推送到音訊流
        self.tts = create_tts_engine(config.tts.type, config, self)
        self.speaking = False

        # 錄製相關狀態
        self.width = self.height = 0
        self.current_record_file = None  # 當前錄製的檔名
        self._init_recording_state()

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
        if isinstance(eventpoint, dict) and "avatar_epoch" in eventpoint:
            if eventpoint["avatar_epoch"] != getattr(self, "_asset_epoch", 0):
                return False
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
                sequence = self._media_sequences.get(key)
                if sequence is None:
                    # Only the current turn's media is accepted; forget old
                    # turns so a long-running session does not grow per turn.
                    sequence = 0
                    while len(self._media_sequences) >= 8:
                        del self._media_sequences[next(iter(self._media_sequences))]
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
        # 檔案音訊按 chunk 切片後送入音訊流。Blocks while decoding and while
        # waiting for queue space: call it from a worker thread.
        input_stream = BytesIO(filebyte)
        stream = self.__create_bytes_stream(input_stream)
        streamlen = stream.shape[0]
        idx=0
        while streamlen >= self.chunk:  #and self.state==State.RUNNING
            self.put_audio_frame(stream[idx:idx+self.chunk],datainfo)
            streamlen -= self.chunk
            idx += self.chunk
    
    def __create_bytes_stream(self,byte_stream):
        with sf.SoundFile(byte_stream) as audio_file:
            # Check the header's length before decoding; read at most the limit.
            limit = int(MAX_AUDIO_FILE_SECONDS * audio_file.samplerate)
            if audio_file.frames > limit:
                raise AudioTooLongError(MAX_AUDIO_FILE_SECONDS)
            sample_rate = audio_file.samplerate
            stream = audio_file.read(frames=limit + 1) # [T*sample_rate,] float64
        if stream.shape[0] > limit:
            raise AudioTooLongError(MAX_AUDIO_FILE_SECONDS)
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
        try:
            while not quit_event.is_set():
                try:
                    self._process_frames_loop(quit_event, loop, audio_track, video_track)
                    break
                except Exception:
                    # One bad frame must not leave the avatar stuck in the
                    # speaking state or silently kill video for the session.
                    logger.exception('[幀處理] 幀處理失敗，結束說話狀態')
                    self.speaking = False
                    time.sleep(0.04)
        finally:
            self.speaking = False
            logger.info('basereal process_frames thread stop')

    def _process_frames_loop(self, quit_event, loop, audio_track, video_track):
        while not quit_event.is_set():
            try:
                result = self.res_frame_queue.get(block=True, timeout=1)
                res_frame,idx,audio_frames = result[:3]
                asset_epoch = result[3] if len(result) > 3 else None
            except queue.Empty:
                continue
            if asset_epoch is not None:
                if asset_epoch != getattr(self, "_asset_epoch", 0):
                    continue
                audio_frames = [(frame, kind, {**(eventpoint or {}), "avatar_epoch": asset_epoch})
                                for frame, kind, eventpoint in audio_frames]
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
            video_eventpoint = dict(turn_events[0]) if turn_events else (
                {"avatar_epoch": asset_epoch} if asset_epoch is not None else None)

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
                    if not self.accepts_media(eventpoint, "renderer_audio_retry"):
                        continue
                    break
            
            # Do not advance visual transition state for a frame that cannot
            # be queued behind direct-audio playback yet.
            if self.direct_audio_enabled:
                audio_queue = getattr(audio_track, "_queue", None)
                if audio_queue is not None and audio_queue.qsize() == 0:
                    continue
            with getattr(self, "_assets_lock", nullcontext()):
                if asset_epoch is not None and asset_epoch != getattr(self, "_asset_epoch", 0):
                    continue
                if audio_frames[0][1] != 0 and audio_frames[1][1] != 0:
                    self.speaking = False
                    audiotype = audio_frames[0][1]
                    if self.custom_index.get(audiotype) is not None:
                        mirindex = self.mirror_index(len(self.custom_img_cycle[audiotype]), self.custom_index[audiotype])
                        combine_frame = self.custom_img_cycle[audiotype][mirindex]
                        self.custom_index[audiotype] += 1
                    else:
                        combine_frame = self.frame_list_cycle[idx]
                else:
                    self.speaking = True
                    try:
                        combine_frame = self.paste_back_frame(res_frame, idx)
                        self.mark_stage_end("avatar_pasteback_done")
                    except Exception as e:
                        logger.warning(f"paste_back_frame error: {e}")
                        continue
                combine_frame = self._compose_avatar_transition(
                    combine_frame, index=idx, is_speech=self.speaking,
                    frame_type=0 if self.speaking else audiotype, eventpoint=video_eventpoint)
                presentation = getattr(self, "_role_presentation", None)
                if presentation is not None:
                    combine_frame = presentation.compose(combine_frame, green_screen=self._green_screen)
                    video_eventpoint = {**(video_eventpoint or {}), **presentation.marker}
                else:
                    combine_frame = limit_video_height(
                        combine_frame, getattr(getattr(self.config, "video", None), "max_height", 0))
                    if getattr(self, "_green_screen", False):
                        from src.scene.service import scene_service
                        combine_frame = scene_service.compose(combine_frame, green_screen=True)
            cv2.putText(combine_frame, "Nova Avatar", (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (128,128,128), 1)
           
            image = combine_frame
            new_frame = VideoFrame.from_ndarray(image, format="bgr24")
            # 子執行緒推送到 WebRTC 佇列
            if not enqueue_media_frame(
                video_track, new_frame, video_eventpoint, loop, quit_event
            ):
                if not self.accepts_media(video_eventpoint, "renderer_video_retry"):
                    continue
                break
            if video_eventpoint is not None:
                self.mark_stage_end("webrtc_video_enqueue")
            self.record_video_data(combine_frame)


    def _init_recording_state(self):
        self.recording = False
        self._record_video_pipe = None
        self._record_audio_pipe = None
        self._record_dir = None
        # Render threads write frames while HTTP handlers start and stop.
        self._record_lock = RLock()

    def _record_paths(self):
        return self._record_dir / 'video.mp4', self._record_dir / 'audio.aac'

    def start_recording(self):
        """開始錄製影片"""
        logger.info(f'[錄製] start_recording 被呼叫, sessionid={self.config.sessionid}')
        with self._record_lock:
            if self.recording:
                logger.warning(f'[錄製] 已經在錄製中，忽略本次呼叫')
                return
            self._record_dir = Path(tempfile.mkdtemp(prefix=f'nova-record-{self.config.sessionid}-'))
            self.recording = True
            # 等到首幀拿到真實尺寸後再啟動 ffmpeg
            if self.width == 0 or self.height == 0:
                logger.info(f'[錄製] 影片尺寸未初始化，將在第一幀資料到達時啟動 ffmpeg 程式')
                return
            self._init_recording_pipes()

    def _init_recording_pipes(self):
        """初始化錄製管道（需要在 width/height 已知後、持有 _record_lock 時呼叫）"""
        if self._record_video_pipe is not None:
            return  # 已經初始化過了

        logger.info(f'[錄製] 初始化 ffmpeg 程式，影片尺寸: {self.width}x{self.height}')
        video_file, audio_file = self._record_paths()
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
                    str(video_file)]
        logger.info(f'[錄製] 啟動影片錄製程式: {" ".join(command)}')
        self._record_video_pipe = subprocess.Popen(
            command, shell=False, stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        acommand = ['ffmpeg',
                    '-y', '-vn',
                    '-f', 's16le',
                    #'-acodec','pcm_s16le',
                    '-ac', '1',
                    '-ar', '16000',
                    '-i', '-',
                    '-acodec', 'aac',
                    #'-f' , 'wav',                  
                    str(audio_file)]
        logger.info(f'[錄製] 啟動音訊錄製程式: {" ".join(acommand)}')
        self._record_audio_pipe = subprocess.Popen(
            acommand, shell=False, stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info(f'[錄製] ffmpeg 程式初始化完成')

    def _write_recording(self, pipe_name: str, data) -> None:
        if not self.recording:
            return
        with self._record_lock:
            if not self.recording:
                return
            if pipe_name == '_record_video_pipe' and self._record_video_pipe is None:
                self._init_recording_pipes()
            pipe = getattr(self, pipe_name)
            if pipe is None:
                return
            try:
                pipe.stdin.write(data.tobytes())
            except (OSError, ValueError) as e:
                logger.warning(f'[錄製] 寫入 ffmpeg 失敗，停止寫入: {e}')
                setattr(self, pipe_name, None)
                self._close_recording_pipes((pipe,))

    def record_video_data(self,image):
        # 首幀到來時寫入真實尺寸
        if self.width == 0:
            self.height,self.width,_ = image.shape
        self._write_recording('_record_video_pipe', image)

    def record_audio_data(self,frame):
        self._write_recording('_record_audio_pipe', frame)

    def _detach_recording(self):
        """End the recording; return its ffmpeg processes and temporary directory."""
        with self._record_lock:
            if not self.recording and self._record_dir is None:
                return None
            self.recording = False
            pipes = (self._record_video_pipe, self._record_audio_pipe)
            self._record_video_pipe = self._record_audio_pipe = None
            directory, self._record_dir = self._record_dir, None
            return pipes, directory

    @staticmethod
    def _close_recording_pipes(pipes, timeout: float = None):
        """Close ffmpeg's stdin and wait for it to finish (blocking); kill it if it hangs."""
        timeout = RECORD_STOP_TIMEOUT_SECONDS if timeout is None else timeout
        for pipe in pipes:
            if pipe is None:
                continue
            try:
                pipe.stdin.close()
            except (OSError, ValueError) as e:
                logger.warning(f'[錄製] 關閉 ffmpeg 輸入失敗: {e}')
            try:
                pipe.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                logger.error(f'[錄製] ffmpeg 未在 {timeout:g} 秒內結束，強制終止')
                pipe.kill()
                pipe.wait()

    @staticmethod
    async def _remove_recording_dir(directory) -> None:
        if directory is not None:
            await asyncio.to_thread(shutil.rmtree, directory, ignore_errors=True)

    async def stop_recording(self):
        """停止錄製並合併音影片；回傳輸出檔路徑，失敗時為 None。"""
        logger.info(f'[錄製] stop_recording 被呼叫, sessionid={self.config.sessionid}')
        detached = self._detach_recording()
        if detached is None:
            logger.warning(f'[錄製] 當前未在錄製狀態，忽略停止請求')
            return None
        pipes, directory = detached
        self.current_record_file = None
        try:
            await asyncio.to_thread(self._close_recording_pipes, pipes)
            video_file, audio_file = directory / 'video.mp4', directory / 'audio.aac'
            if not video_file.is_file() or not audio_file.is_file():
                logger.error(f'[錄製] ffmpeg 未產生暫存檔（可能尚未收到第一幀資料）')
                return None
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            await asyncio.to_thread(RECORDS_DIR.mkdir, parents=True, exist_ok=True)
            output_file = RECORDS_DIR / f'record_{timestamp}_session{self.config.sessionid}.mp4'
            returncode = await _run_ffmpeg(
                '-y', '-i', str(audio_file), '-i', str(video_file),
                '-c:v', 'copy', '-c:a', 'copy', str(output_file),
            )
            if returncode != 0 or not output_file.is_file():
                logger.error(f'[錄製] ✗ 合併失敗 returncode={returncode}: {output_file}')
                output_file.unlink(missing_ok=True)
                return None
            logger.info(f'[錄製] ✓ 錄製完成! 輸出檔案: {output_file}')
            self.current_record_file = str(output_file)
            return self.current_record_file
        finally:
            await self._remove_recording_dir(directory)

    async def discard_recording(self):
        """Stop an unfinished recording without keeping it (the session is closing)."""
        detached = self._detach_recording()
        if detached is None:
            return
        pipes, directory = detached
        logger.info(f'[錄製] 工作階段關閉，捨棄未完成的錄製 sessionid={self.config.sessionid}')
        try:
            await asyncio.to_thread(self._close_recording_pipes, pipes)
        finally:
            await self._remove_recording_dir(directory)
