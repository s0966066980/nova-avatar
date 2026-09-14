import math
import torch
import numpy as np

#from .utils import *
import subprocess
import os
import time
import torch.nn.functional as F
import cv2
import glob
import pickle
import copy

import queue
from queue import Queue
from threading import Thread, Event
import torch.multiprocessing as mp

from src.avatars.musetalk.utils.utils import get_file_type,get_video_fps,datagen
#from musetalk.utils.preprocessing import get_landmark_and_bbox,read_imgs,coord_placeholder
from src.avatars.musetalk.myutil import get_image_blending
from src.avatars.mouth_quality import enhance_from_config
from src.avatars.musetalk.utils.utils import load_all_model
from src.avatars.musetalk.whisper.audio2feature import Audio2Feature

from src.avatars.musetalk.audio_stream_handler import (
    MuseAudioStreamHandler,
    MuseInferenceBatch,
)
import asyncio
from av import AudioFrame, VideoFrame
from src.avatars.base import BaseAvatar

from tqdm import tqdm
from src.utils.logging import logger

MIN_VIDEO_BUFFER_FRAMES = 5
MAX_TTS_AUDIO_WAIT_SECONDS = 0.20
MOUTH_ACTIVITY_THRESHOLD = 1e-4


def _result_audio_frames(item):
    if not isinstance(item, tuple) or len(item) < 3:
        return ()
    audio_frames = item[2]
    return audio_frames if isinstance(audio_frames, (list, tuple)) else ()


def _starts_speech(item) -> bool:
    return any(
        isinstance(eventpoint, dict) and eventpoint.get("status") == "start"
        for _frame, _frame_type, eventpoint in _result_audio_frames(item)
    )


def _is_unscoped_idle_result(item) -> bool:
    audio_frames = _result_audio_frames(item)
    return bool(audio_frames) and all(
        frame_type != 0
        and not (
            isinstance(eventpoint, dict) and eventpoint.get("turn_id")
        )
        for _frame, frame_type, eventpoint in audio_frames
    )


def _discard_leading_idle_results(result_queue) -> int:
    """Remove only pre-speech idle runway already superseded by an onset.

    MuseTalk can render ahead by the full bounded result queue while idle. A
    first speech result appended behind that runway waits roughly 0.5 seconds
    before its paired PCM and mouth frame reach WebRTC. The WebRTC tracks
    already own a bounded idle runway, so retaining this second copy adds
    latency without preventing starvation.
    """
    mutex = getattr(result_queue, "mutex", None)
    storage = getattr(result_queue, "queue", None)
    if mutex is None or storage is None:
        return 0
    with mutex:
        discarded = 0
        while storage and _is_unscoped_idle_result(storage[0]):
            storage.popleft()
            discarded += 1
        if discarded:
            unfinished = getattr(result_queue, "unfinished_tasks", 0)
            result_queue.unfinished_tasks = max(0, unfinished - discarded)
            result_queue.not_full.notify_all()
            if result_queue.unfinished_tasks == 0:
                result_queue.all_tasks_done.notify_all()
        return discarded


def put_result_frame(result_queue, item, quit_event) -> bool:
    """Bounded put that lets MuseTalk inference stop even when playback is gone."""
    if quit_event.is_set():
        return False
    if _starts_speech(item):
        _discard_leading_idle_results(result_queue)
    elif _is_unscoped_idle_result(item):
        # Idle rendering may run faster than the 25 fps WebRTC consumer. A
        # full idle queue already contains enough runway, so blocking the
        # inference thread here only prevents a newly ready speech batch from
        # overtaking redundant idle work.
        try:
            result_queue.put_nowait(item)
        except queue.Full:
            pass
        return True
    while not quit_event.is_set():
        try:
            result_queue.put(item, block=True, timeout=0.1)
            return True
        except queue.Full:
            continue
    return False


def should_wait_for_tts_audio(
    tts_pending: bool,
    queued_audio_frames: int,
    required_audio_frames: int,
    queued_video_frames: int,
    pending_wait_seconds: float = 0.0,
    max_wait_seconds: float = MAX_TTS_AUDIO_WAIT_SECONDS,
) -> bool:
    """Briefly protect a partial batch without freezing idle video output."""
    return (
        tts_pending
        and pending_wait_seconds < max_wait_seconds
        and queued_audio_frames < required_audio_frames
        and (
            queued_audio_frames > 0
            or queued_video_frames >= MIN_VIDEO_BUFFER_FRAMES
        )
    )


def is_audible_speech_frame(frame: np.ndarray, frame_type: int) -> bool:
    """Return whether one PCM frame should drive a generated mouth pose."""
    samples = np.asarray(frame)
    return (
        frame_type == 0
        and samples.size > 0
        and float(np.max(np.abs(samples))) > MOUTH_ACTIVITY_THRESHOLD
    )


def _media_batch_is_current(audio_frames, media_guard, stage: str) -> bool:
    if media_guard is None:
        return True
    turn_events = [
        eventpoint
        for _frame, _frame_type, eventpoint in audio_frames
        if isinstance(eventpoint, dict) and eventpoint.get("turn_id")
    ]
    return not turn_events or all(
        media_guard(eventpoint, stage) for eventpoint in turn_events
    )


def load_model():
    # load model weights
    vae, unet, pe = load_all_model()
    device = torch.device("cuda" if torch.cuda.is_available() else ("mps" if (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()) else "cpu"))
    timesteps = torch.tensor([0], device=device)
    pe = pe.half().to(device)
    vae.vae = vae.vae.half().to(device)
    #vae.vae.share_memory().to(device)
    unet.model = unet.model.half().to(device)
    #unet.model.share_memory()
    # Initialize audio processor and Whisper model
    audio_processor = Audio2Feature(model_path="./models/musetalk/whisper")
    return vae, unet, pe, timesteps, audio_processor

def load_avatar(avatar_id):
    #self.video_path = '' #video_path
    #self.bbox_shift = opt.bbox_shift
    avatar_path = f"./data/avatars/{avatar_id}"
    full_imgs_path = f"{avatar_path}/full_imgs" 
    coords_path = f"{avatar_path}/coords.pkl"
    latents_out_path= f"{avatar_path}/latents.pt"
    video_out_path = f"{avatar_path}/vid_output/"
    mask_out_path =f"{avatar_path}/mask"
    mask_coords_path =f"{avatar_path}/mask_coords.pkl"
    avatar_info_path = f"{avatar_path}/avator_info.json"
    required = [latents_out_path, coords_path, mask_coords_path, full_imgs_path, mask_out_path]
    missing = [p for p in required if not os.path.exists(p)]
    if missing:
        raise FileNotFoundError(
            f"MuseTalk 數字人素材不完整: {avatar_path}\n"
            f"缺少: {', '.join(missing)}\n"
            "請先用閉嘴正面影片生成素材:\n"
            f"  uv run python src/avatars/musetalk/genavatar_musetalk.py "
            f"--avatar_id {avatar_id} --file /path/to/silent_video.mp4"
        )

    input_latent_list_cycle = torch.load(latents_out_path)  #,weights_only=True
    with open(coords_path, 'rb') as f:
        coord_list_cycle = pickle.load(f)
    input_img_list = glob.glob(os.path.join(full_imgs_path, '*.[jpJP][pnPN]*[gG]'))
    input_img_list = sorted(input_img_list, key=lambda x: int(os.path.splitext(os.path.basename(x))[0]))
    frame_list_cycle = read_imgs(input_img_list)
    with open(mask_coords_path, 'rb') as f:
        mask_coords_list_cycle = pickle.load(f)
    input_mask_list = glob.glob(os.path.join(mask_out_path, '*.[jpJP][pnPN]*[gG]'))
    input_mask_list = sorted(input_mask_list, key=lambda x: int(os.path.splitext(os.path.basename(x))[0]))
    mask_list_cycle = read_imgs(input_mask_list)
    return frame_list_cycle,mask_list_cycle,coord_list_cycle,mask_coords_list_cycle,input_latent_list_cycle

@torch.no_grad()
def warm_up(batch_size,model):
    # 預熱函式
    logger.info('warmup model...')
    vae, unet, pe, timesteps, audio_processor = model
    #batch_size = 16
    #timesteps = torch.tensor([0], device=unet.device)
    whisper_batch = np.ones((batch_size, 50, 384), dtype=np.uint8)
    latent_batch = torch.ones(batch_size, 8, 32, 32).to(unet.device)

    audio_feature_batch = torch.from_numpy(whisper_batch)
    audio_feature_batch = audio_feature_batch.to(device=unet.device, dtype=unet.model.dtype)
    audio_feature_batch = pe(audio_feature_batch)
    latent_batch = latent_batch.to(dtype=unet.model.dtype)
    pred_latents = unet.model(latent_batch,
                              timesteps,
                              encoder_hidden_states=audio_feature_batch).sample
    vae.decode_latents(pred_latents)

def read_imgs(img_list):
    frames = []
    logger.info('reading images...')
    for img_path in tqdm(img_list):
        frame = cv2.imread(img_path)
        frames.append(frame)
    return frames

def __mirror_index(size, index):
    #size = len(self.coord_list_cycle)
    turn = index // size
    res = index % size
    if turn % 2 == 0:
        return res
    else:
        return size - res - 1 

@torch.no_grad()
def inference(quit_event,batch_size,input_latent_list_cycle,audio_feat_queue,audio_out_queue,res_frame_queue,
              vae, unet, pe,timesteps, media_guard=None, on_stale_drop=None,
              on_stage_end=None): #vae, unet, pe,timesteps
    
    # vae, unet, pe = load_diffusion_model()
    # device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    # timesteps = torch.tensor([0], device=device)
    # pe = pe.half()
    # vae.vae = vae.vae.half()
    # unet.model = unet.model.half()
    
    length = len(input_latent_list_cycle)
    index = 0
    count=0
    counttime=0
    first_result_turns = set()

    def mark_first_result(paired_audio) -> None:
        if on_stage_end is None:
            return
        turn_ids = {
            str(eventpoint.get("turn_id"))
            for _frame, _frame_type, eventpoint in paired_audio
            if isinstance(eventpoint, dict) and eventpoint.get("turn_id")
        }
        for turn_id in turn_ids:
            if turn_id not in first_result_turns:
                on_stage_end("musetalk_inference_first_result")
                first_result_turns.add(turn_id)
    logger.info('start inference')
    while not quit_event.is_set():
        starttime=time.perf_counter()
        try:
            feature_item = audio_feat_queue.get(block=True, timeout=1)
        except queue.Empty:
            continue
        if isinstance(feature_item, MuseInferenceBatch):
            whisper_chunks = feature_item.features
            audio_frames = list(feature_item.audio_frames)
            effective_batch_size = int(feature_item.batch_size or batch_size)
            if not _media_batch_is_current(
                audio_frames,
                media_guard,
                "musetalk_batch",
            ):
                if on_stale_drop is not None:
                    on_stale_drop("musetalk_batch", "stale_generation")
                continue
        else:
            whisper_chunks = feature_item
            audio_frames = []
            effective_batch_size = batch_size
        is_all_silence=True
        for _ in range(len(audio_frames), effective_batch_size * 2):
            audio_frames.append(audio_out_queue.get())
        normalized_audio_frames = []
        for frame,frame_type,eventpoint in audio_frames:
            if frame_type == 0 and not is_audible_speech_frame(frame, frame_type):
                frame_type = 1
            normalized_audio_frames.append((frame,frame_type,eventpoint))
            if frame_type==0:
                is_all_silence=False
        audio_frames = normalized_audio_frames
        if is_all_silence:
            for i in range(effective_batch_size):
                paired_audio = audio_frames[i*2:i*2+2]
                if not _media_batch_is_current(
                    paired_audio,
                    media_guard,
                    "musetalk_result",
                ):
                    if on_stale_drop is not None:
                        on_stale_drop("musetalk_result", "stale_generation")
                    break
                if not put_result_frame(
                    res_frame_queue,
                    (None,__mirror_index(length,index),paired_audio),
                    quit_event,
                ):
                    break
                mark_first_result(paired_audio)
                index = index + 1
        else:
            # print('infer=======')
            t=time.perf_counter()
            whisper_batch = np.stack(whisper_chunks)
            latent_batch = []
            for i in range(effective_batch_size):
                idx = __mirror_index(length,index+i)
                latent = input_latent_list_cycle[idx]
                latent_batch.append(latent)
            latent_batch = torch.cat(latent_batch, dim=0)
            
            # for i, (whisper_batch,latent_batch) in enumerate(gen):
            audio_feature_batch = torch.from_numpy(whisper_batch)
            audio_feature_batch = audio_feature_batch.to(device=unet.device,
                                                            dtype=unet.model.dtype)
            audio_feature_batch = pe(audio_feature_batch)
            latent_batch = latent_batch.to(dtype=unet.model.dtype)
            # print('prepare time:',time.perf_counter()-t)
            # t=time.perf_counter()

            pred_latents = unet.model(latent_batch, 
                                        timesteps, 
                                        encoder_hidden_states=audio_feature_batch).sample
            # print('unet time:',time.perf_counter()-t)
            # t=time.perf_counter()
            recon = vae.decode_latents(pred_latents)
            # infer_inqueue.put((whisper_batch,latent_batch,sessionid))
            # recon,outsessionid = infer_outqueue.get()
            # if outsessionid != sessionid:
            #     print('outsessionid:',outsessionid,' mysessionid:',sessionid)

            # print('vae time:',time.perf_counter()-t)
            #print('diffusion len=',len(recon))
            counttime += (time.perf_counter() - t)
            count += effective_batch_size
            #_totalframe += 1
            if count>=100:
                logger.info(f"------actual avg infer fps:{count/counttime:.4f}")
                count=0
                counttime=0
            for i,res_frame in enumerate(recon):
                #self.__pushmedia(res_frame,loop,audio_track,video_track)
                paired_audio = audio_frames[i*2:i*2+2]
                if not _media_batch_is_current(
                    paired_audio,
                    media_guard,
                    "musetalk_result",
                ):
                    if on_stale_drop is not None:
                        on_stale_drop("musetalk_result", "stale_generation")
                    break
                output_frame = (
                    res_frame
                    if any(frame_type == 0 for _, frame_type, _ in paired_audio)
                    else None
                )
                if not put_result_frame(
                    res_frame_queue,
                    (output_frame,__mirror_index(length,index),paired_audio),
                    quit_event,
                ):
                    break
                mark_first_result(paired_audio)
                index = index + 1
            #print('total batch time:',time.perf_counter()-starttime)            
    logger.info('musereal inference processor stop')

class MuseTalkAvatar(BaseAvatar):
    @torch.no_grad()
    def __init__(self, config, model, avatar):
        super().__init__(config)
        #self.opt = opt # shared with the trainer's opt to support in-place modification of rendering parameters.
        # self.W = opt.W
        # self.H = opt.H

        self.fps = config.audio.fps # 20 ms per frame

        self.batch_size = config.model.batch_size
        self.idx = 0
        # Render and inference both run as threads in this process; avoid
        # multiprocessing serialization for generated frames.
        self.res_frame_queue = queue.Queue(self.batch_size * 2)

        self.vae, self.unet, self.pe, self.timesteps, self.audio_processor = model
        self.frame_list_cycle,self.mask_list_cycle,self.coord_list_cycle,self.mask_coords_list_cycle, self.input_latent_list_cycle = avatar
        from .mouth_continuity import MouthContinuityController
        from .avatar_transition import AvatarTransitionController

        musetalk_cfg = getattr(config.model, "musetalk", None)
        self.max_tts_audio_wait_seconds = float(
            getattr(musetalk_cfg, "max_tts_audio_wait_seconds", 0.35) or 0.35
        )
        mouth_continuity_enabled = bool(
            getattr(
                musetalk_cfg,
                "mouth_continuity",
                True,
            )
        )
        gap_grace = int(getattr(musetalk_cfg, "gap_grace_frames", 1) or 1)
        opening = int(getattr(musetalk_cfg, "opening_frames", 2) or 2)
        closing = int(getattr(musetalk_cfg, "closing_frames", 4) or 4)
        align_idle_return = bool(
            getattr(musetalk_cfg, "mouth_continuity_idle_alignment", True)
        )
        settling_enabled = bool(
            getattr(musetalk_cfg, "settling_enabled", True)
        )
        settling_frames = max(
            1,
            int(getattr(musetalk_cfg, "settling_frames", 5) or 5),
        )
        self._mouth_continuity = (
            MouthContinuityController(
                self.frame_list_cycle,
                self.mask_list_cycle,
                self.mask_coords_list_cycle,
                gap_grace_frames=gap_grace,
                opening_frames=opening,
                closing_frames=closing,
                settling_frames=settling_frames if settling_enabled else None,
                align_idle_return=align_idle_return,
            )
            if mouth_continuity_enabled
            else None
        )
        if bool(getattr(musetalk_cfg, "avatar_transition", True)):
            min_frames = int(getattr(musetalk_cfg, "settling_min_frames", settling_frames) or settling_frames)
            max_frames = int(getattr(musetalk_cfg, "settling_max_frames", settling_frames) or settling_frames)
            self._avatar_transition = AvatarTransitionController(
                self.frame_list_cycle, self.mask_list_cycle, self.mask_coords_list_cycle,
                self.coord_list_cycle, mouth_controller=self._mouth_continuity,
                fps=getattr(config.video, "fps", 25), settling_min_frames=min_frames,
                settling_max_frames=max_frames,
                phase_matching_enabled=bool(getattr(musetalk_cfg, "phase_matching_enabled", True)),
                phase_temporal_penalty=float(getattr(musetalk_cfg, "phase_temporal_penalty", 0.015)),
                micro_crossfade_enabled=bool(getattr(musetalk_cfg, "micro_crossfade_enabled", True)),
                micro_crossfade_frames=int(getattr(musetalk_cfg, "micro_crossfade_frames", 2)),
                micro_crossfade_fullframe_max_diff=float(getattr(musetalk_cfg, "micro_crossfade_fullframe_max_diff", 18.0)),
                opening_frames=opening,
            )
        #self.__loadavatar()

        self.audio_stream = MuseAudioStreamHandler(config, self, self.audio_processor)
        self.audio_stream.warm_up()
        
        self.render_event = mp.Event()

    # def __del__(self):
    #     logger.info(f'musereal({self.sessionid}) delete')
    

    def __mirror_index(self, index):
        size = len(self.coord_list_cycle)
        turn = index // size
        res = index % size
        if turn % 2 == 0:
            return res
        else:
            return size - res - 1  

    def __warm_up(self): 
        self.audio_stream.run_step()
        whisper_chunks = self.audio_stream.get_next_feat()
        whisper_batch = np.stack(whisper_chunks)
        latent_batch = []
        for i in range(self.batch_size):
            idx = self.__mirror_index(self.idx+i)
            latent = self.input_latent_list_cycle[idx]
            latent_batch.append(latent)
        latent_batch = torch.cat(latent_batch, dim=0)
        logger.info('infer=======')
        # for i, (whisper_batch,latent_batch) in enumerate(gen):
        audio_feature_batch = torch.from_numpy(whisper_batch)
        audio_feature_batch = audio_feature_batch.to(device=self.unet.device,
                                                        dtype=self.unet.model.dtype)
        audio_feature_batch = self.pe(audio_feature_batch)
        latent_batch = latent_batch.to(dtype=self.unet.model.dtype)

        pred_latents = self.unet.model(latent_batch, 
                                    self.timesteps, 
                                    encoder_hidden_states=audio_feature_batch).sample
        recon = self.vae.decode_latents(pred_latents)
      

    def paste_back_frame(self,pred_frame,idx:int):
        bbox = self.coord_list_cycle[idx]
        ori_frame = copy.deepcopy(self.frame_list_cycle[idx])
        x1, y1, x2, y2 = bbox

        res_frame = enhance_from_config(
            pred_frame, (x2 - x1, y2 - y1), self.config
        )
        mask = self.mask_list_cycle[idx]
        mask_crop_box = self.mask_coords_list_cycle[idx]

        combine_frame = get_image_blending(ori_frame,res_frame,bbox,mask,mask_crop_box)
        return combine_frame
            
    def render(self,quit_event,loop=None,audio_track=None,video_track=None):
        #if self.opt.asr:
        #     self.audio_stream.warm_up()

        self.init_customindex()
        self.tts.render(quit_event)
        
        #self.render_event.set() #start infer process render
        infer_quit_event = Event()
        infer_thread = Thread(target=inference, args=(infer_quit_event,self.batch_size,self.input_latent_list_cycle,
                                           self.audio_stream.feat_queue,self.audio_stream.output_queue,self.res_frame_queue,
                                           self.vae, self.unet, self.pe,self.timesteps,
                                           self.accepts_media,self.record_stale_drop,
                                           self.mark_stage_end)) #mp.Process
        infer_thread.start()
        
        process_quit_event = Event()
        process_thread = Thread(target=self.process_frames, args=(process_quit_event,loop,audio_track,video_track))
        process_thread.start()

        
        count=0
        totaltime=0
        _starttime=time.perf_counter()
        tts_wait_started_at = None
        #_totalframe=0
        while not quit_event.is_set(): #todo
            # update texture every frame
            # audio stream thread...
            video_queue_size = video_track._queue.qsize() if video_track else 0
            required_audio_frames = (
                self.batch_size * 2
                if self.audio_stream.startup_batch_emitted
                else self.audio_stream.startup_batch_size * 2
            )
            tts_pending = self.tts.has_pending_work()
            queued_audio_frames = self.audio_stream.queue.qsize()
            now = time.perf_counter()
            if not tts_pending or queued_audio_frames >= required_audio_frames:
                tts_wait_started_at = None
            elif tts_wait_started_at is None:
                tts_wait_started_at = now
            pending_wait_seconds = (
                0.0
                if tts_wait_started_at is None
                else now - tts_wait_started_at
            )
            if should_wait_for_tts_audio(
                tts_pending,
                queued_audio_frames,
                required_audio_frames,
                video_queue_size,
                pending_wait_seconds,
                max_wait_seconds=self.max_tts_audio_wait_seconds,
            ):
                time.sleep(0.01)
                continue
            if tts_pending and queued_audio_frames < required_audio_frames:
                # Let one idle/partial batch advance after the bounded hold,
                # then grant the next fragment a fresh short coalescing window.
                tts_wait_started_at = None

            t = time.perf_counter()
            self.audio_stream.run_step()
            #self.test_step(loop,audio_track,video_track)
            # totaltime += (time.perf_counter() - t)
            # count += self.opt.batch_size
            # if count>=100:
            #     print(f"------actual avg infer fps:{count/totaltime:.4f}")
            #     count=0
            #     totaltime=0
            if video_track and video_track._queue.qsize() >= MIN_VIDEO_BUFFER_FRAMES:
                logger.debug('sleep qsize=%d',video_track._queue.qsize())
                time.sleep(0.04*video_track._queue.qsize()*0.8)
            # if video_track._queue.qsize()>=5:
            #     print('sleep qsize=',video_track._queue.qsize())
            #     time.sleep(0.04*video_track._queue.qsize()*0.8)
                
            # delay = _starttime+_totalframe*0.04-time.perf_counter() #40ms
            # if delay > 0:
            #     time.sleep(delay)
        logger.info('musereal thread stop')

        infer_quit_event.set()
        process_quit_event.set()
        infer_thread.join()

        process_thread.join()
            
