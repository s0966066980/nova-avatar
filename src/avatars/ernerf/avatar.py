# Modified by HongXian0903 for Nova Avatar integration, 2026.
# Third-party terms remain applicable; see THIRD_PARTY_NOTICES.md.

import math
import torch
import numpy as np

import os
import time
import torch.nn.functional as F
import cv2
import glob

from .audio_stream_handler import ERNeRFAudioStreamHandler

import asyncio
from av import AudioFrame, VideoFrame
from src.avatars.base import BaseAvatar

from .nerf_triplane.provider import NeRFDataset_Test
from .nerf_triplane.utils import *
from .nerf_triplane.network import NeRFNetwork
from transformers import AutoModelForCTC, AutoProcessor, Wav2Vec2Processor, HubertModel

from src.utils.logging import logger
def read_imgs(img_list):
    frames = []
    logger.info('reading images...')
    for img_path in tqdm(img_list):
        frame = cv2.imread(img_path)
        frames.append(frame)
    return frames

def load_model(config):
    config.model.ernerf.test = True
    config.model.ernerf.test_train = False
    config.model.ernerf.smooth_path = True
    config.model.ernerf.smooth_lips = True

    assert config.model.ernerf.pose != '', 'Must provide a pose source'

    config.model.ernerf.fp16 = True
    config.model.ernerf.cuda_ray = True
    config.model.ernerf.exp_eye = True
    config.model.ernerf.smooth_eye = True

    if config.model.ernerf.torso_imgs == '':
        config.model.ernerf.torso = True

    config.model.ernerf.asr = True

    if config.model.ernerf.patch_size > 1:
        assert config.model.ernerf.num_rays % (config.model.ernerf.patch_size ** 2) == 0, "patch_size ** 2 should be dividable by num_rays."
    seed_everything(config.model.ernerf.seed)
    logger.info(config)

    device = torch.device('cuda' if torch.cuda.is_available() else ('mps' if (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()) else 'cpu'))
    model = NeRFNetwork(config.model.ernerf)

    criterion = torch.nn.MSELoss(reduction='none')
    metrics = []
    logger.info(model)
    trainer = Trainer('ngp', config.model.ernerf, model, device=device, workspace=config.model.ernerf.workspace, criterion=criterion, fp16=config.model.ernerf.fp16, metrics=metrics, use_checkpoint=config.model.ernerf.ckpt)

    test_loader = NeRFDataset_Test(config.model.ernerf, device=device).dataloader()
    model.aud_features = test_loader._data.auds
    model.eye_areas = test_loader._data.eye_area

    logger.info(f'[INFO] loading ASR model {config.model.ernerf.asr_model}...')
    if 'hubert' in config.model.ernerf.asr_model:
        audio_processor = Wav2Vec2Processor.from_pretrained(config.model.ernerf.asr_model)
        audio_model = HubertModel.from_pretrained(config.model.ernerf.asr_model).to(device) 
    else:   
        audio_processor = AutoProcessor.from_pretrained(config.model.ernerf.asr_model)
        audio_model = AutoModelForCTC.from_pretrained(config.model.ernerf.asr_model).to(device)
    return trainer,test_loader,audio_processor,audio_model

def load_avatar(config):
    fullbody_list_cycle = None
    if config.model.ernerf.fullbody:
        input_img_list = glob.glob(os.path.join(config.model.ernerf.fullbody_img, '*.[jpJP][pnPN]*[gG]'))
        input_img_list = sorted(input_img_list, key=lambda x: int(os.path.splitext(os.path.basename(x))[0]))
        fullbody_list_cycle = read_imgs(input_img_list)
    return fullbody_list_cycle

class ERNeRFAvatar(BaseAvatar):
    def __init__(self, config, model, avatar, debug=True):
        super().__init__(config)
        
        self.W = config.video.width
        self.H = config.video.height
        
        self.width = config.video.width
        self.height = config.video.height
        logger.info(f'[ERNeRF] 影片尺寸已初始化: {self.width}x{self.height}')

        self.trainer, self.data_loader, audio_processor,audio_model = model

        self.loader = iter(self.data_loader)
        frame_total_num = self.data_loader._data.end_index
        self.fullbody_list_cycle = avatar
    
        self.audio_stream = ERNeRFAudioStreamHandler(config, self, audio_processor, audio_model)
        self.audio_stream.warm_up()

    def __del__(self):
        logger.info(f'ERNeRFAvatar({self.sessionid}) delete')    

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.config.model.ernerf.asr:
            self.audio_stream.stop()  


    def test_step(self,loop=None,audio_track=None,video_track=None):
        

        try:
            data = next(self.loader)
        except StopIteration:
            self.loader = iter(self.data_loader)
            data = next(self.loader)
        
        if self.config.model.ernerf.asr:
            data['auds'] = self.audio_stream.get_next_feat()

        audiotype1 = 0
        audiotype2 = 0
        for i in range(2):
            frame,type,eventpoint = self.audio_stream.get_audio_out()
            if i==0:
                audiotype1 = type
            else:
                audiotype2 = type
            frame_int16 = (frame * 32767).astype(np.int16)
            new_frame = AudioFrame(format='s16', layout='mono', samples=frame_int16.shape[0])
            new_frame.planes[0].update(frame_int16.tobytes())
            new_frame.sample_rate=16000
            asyncio.run_coroutine_threadsafe(audio_track._queue.put((new_frame,eventpoint)), loop)
            self.record_audio_data(frame_int16)

        if audiotype1 != 0 and audiotype2 != 0:
            self.speaking = False
        else:
            self.speaking = True

        if audiotype1 != 0 and audiotype2 != 0 and self.custom_index.get(audiotype1) is not None:
            mirindex = self.mirror_index(len(self.custom_img_cycle[audiotype1]), self.custom_index[audiotype1])
            image = self.custom_img_cycle[audiotype1][mirindex]
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            self.custom_index[audiotype1] += 1
            new_frame = VideoFrame.from_ndarray(image_rgb, format="rgb24")
            asyncio.run_coroutine_threadsafe(video_track._queue.put((new_frame, None)), loop)
            self.record_video_data(image)
        else:
            outputs = self.trainer.test_gui_with_data(data, self.W, self.H)
            image = (outputs['image'] * 255).astype(np.uint8)
            if not self.config.model.ernerf.fullbody:
                new_frame = VideoFrame.from_ndarray(image, format="rgb24")
                asyncio.run_coroutine_threadsafe(video_track._queue.put((new_frame, None)), loop)
                image_bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
                self.record_video_data(image_bgr)
            else:
                image_fullbody = self.fullbody_list_cycle[data['index'][0]]
                image_fullbody_rgb = cv2.cvtColor(image_fullbody, cv2.COLOR_BGR2RGB)
                start_x = self.config.model.ernerf.fullbody_offset_x
                start_y = self.config.model.ernerf.fullbody_offset_y
                image_fullbody_rgb[start_y:start_y+image.shape[0], start_x:start_x+image.shape[1]] = image
                new_frame = VideoFrame.from_ndarray(image_fullbody_rgb, format="rgb24")
                asyncio.run_coroutine_threadsafe(video_track._queue.put((new_frame, None)), loop)
                image_fullbody[start_y:start_y+image.shape[0], start_x:start_x+image.shape[1]] = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
                self.record_video_data(image_fullbody)

            
    def render(self,quit_event,loop=None,audio_track=None,video_track=None):
        self.init_customindex()

        count=0
        totaltime=0
        _starttime=time.perf_counter()
        _totalframe=0

        self.tts.render(quit_event)
        while not quit_event.is_set():
            t = time.perf_counter()
            for _ in range(2):  # 音訊 50FPS，影片 25FPS，每幀跑 2 次 ASR
                self.audio_stream.run_step()
            self.test_step(loop,audio_track,video_track)
            totaltime += (time.perf_counter() - t)
            count += 1
            _totalframe += 1
            if count==100:
                logger.info(f"------actual avg infer fps:{count/totaltime:.4f}")
                count=0
                totaltime=0
            if video_track._queue.qsize() >= 5:
                time.sleep(0.04 * video_track._queue.qsize() * 0.8)
        logger.info('ERNeRFAvatar thread stop')

