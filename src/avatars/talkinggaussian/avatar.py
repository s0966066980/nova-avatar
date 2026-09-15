# Derived from Kedreamix/Linly-Talker-Stream.
# Copyright [Linly-talker-stream@kedreamix].
# Licensed under the Apache License, Version 2.0.
#
# Modified by HongXian0903, 2026.
# See LICENSE, NOTICE, and THIRD_PARTY_NOTICES.md.


"""
TalkingGaussian Avatar Implementation
基於 synthesize_fuse.py 的推理邏輯
"""
import os
import torch
import numpy as np
import time
import cv2
import copy

import queue
from queue import Queue
from threading import Thread, Event
import torch.nn.functional as F

import asyncio
from av import AudioFrame, VideoFrame
from src.avatars.base import BaseAvatar
from src.utils.logging import logger

# TalkingGaussian 相關匯入 - 使用相對匯入
from .scene import Scene
from .gaussian_renderer import render_motion, render_motion_mouth
from .gaussian_renderer import GaussianModel, MotionNetwork, MouthMotionNetwork
from .arguments import ModelParams, PipelineParams
from .utils.camera_utils import loadCamOnTheFly
from argparse import Namespace, ArgumentParser
from .audio_stream_handler import TalkingGaussianAudioStreamHandler


def dilate_fn(bin_img, ksize=13):
    """膨脹函式，用於處理 mouth alpha"""
    pad = (ksize - 1) // 2
    out = F.max_pool2d(bin_img, kernel_size=ksize, stride=1, padding=pad)
    return out


def load_model(config):
    """
    載入 TalkingGaussian 模型
    """
    logger.info(f'Loading TalkingGaussian model... from config: {config.model.talkinggaussian.model_path}')
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    
    # 建立 parser 和引陣列
    parser = ArgumentParser(description="TalkingGaussian Avatar")
    model_params = ModelParams(parser)
    pipeline_params = PipelineParams(parser)
    
    # 優先讀取訓練時儲存的 cfg_args（如果存在）
    cfg_args_path = os.path.join(config.talkinggaussian.model_path, "cfg_args")
    if os.path.exists(cfg_args_path):
        logger.info(f'Loading saved config from {cfg_args_path}')
        with open(cfg_args_path, 'r') as f:
            cfg_string = f.read()
        try:
            args = eval(cfg_string)
            logger.info('Loaded config from cfg_args')
        except Exception as e:
            logger.warning(f'Failed to load cfg_args: {e}, using defaults')
            args = Namespace()
    else:
        logger.info('cfg_args not found, using defaults')
        args = Namespace()
    
    args.model_path = config.talkinggaussian.model_path
    args.source_path = config.talkinggaussian.source_path
    args.bg_img = config.talkinggaussian.bg_img  # 傳遞背景配置
    
    dataset = model_params.extract(args)
    pipeline = pipeline_params.extract(args)
    
    # 確保 pipeline 物件有 debug 屬性
    if not hasattr(pipeline, 'debug'):
        pipeline.debug = False
    if not hasattr(pipeline, 'convert_SHs_python'):
        pipeline.convert_SHs_python = False
    if not hasattr(pipeline, 'compute_cov3D_python'):
        pipeline.compute_cov3D_python = False

    dataset.eval = args.eval = True    
    
    dataset.image_width = config.video.width
    dataset.image_height = config.video.height

    logger.info(f'Model config: source_path={dataset.source_path}, model_path={dataset.model_path}')
    with torch.no_grad():
        # 建立 Gaussian 模型
        gaussians = GaussianModel(dataset.sh_degree)
        gaussians_mouth = GaussianModel(dataset.sh_degree)
        
        # 載入場景
        scene = Scene(dataset, gaussians, shuffle=False)
        
        # 建立運動網路
        motion_net = MotionNetwork(args=dataset).cuda()
        motion_net_mouth = MouthMotionNetwork(args=dataset).cuda()
        
        # 載入 checkpoint
        checkpoint_path = os.path.join(dataset.model_path, "chkpnt_fuse_latest.pth")
        logger.info(f'Loading checkpoint from {checkpoint_path}')
        
        if not os.path.exists(checkpoint_path):
            logger.error(f'Checkpoint not found: {checkpoint_path}')
            raise FileNotFoundError(f'Checkpoint not found: {checkpoint_path}')
        
        (model_params, motion_params, model_mouth_params, motion_mouth_params) = torch.load(checkpoint_path)
        motion_net.load_state_dict(motion_params, strict=False)
        gaussians.restore(model_params, None)
        motion_net_mouth.load_state_dict(motion_mouth_params, strict=False)
        gaussians_mouth.restore(model_mouth_params, None)
        
        # 設定背景顏色
        bg_color = [1, 1, 1] if dataset.white_background else [0, 0, 0]
        background = torch.tensor(bg_color, dtype=torch.float32, device="cuda")
    
    logger.info('TalkingGaussian model loaded successfully')
    

    # 載入 ASR 模型用於音訊特徵提取
    logger.info(f'[INFO] loading ASR model {config.model.ernerf.asr_model}...')
    if 'hubert' in config.model.ernerf.asr_model:
        from transformers import Wav2Vec2Processor, HubertModel
        audio_processor = Wav2Vec2Processor.from_pretrained(config.model.ernerf.asr_model)
        audio_model = HubertModel.from_pretrained(config.model.ernerf.asr_model).to(device) 
    else:   
        from transformers import AutoProcessor, AutoModelForCTC
        audio_processor = AutoProcessor.from_pretrained(config.model.ernerf.asr_model)
        audio_model = AutoModelForCTC.from_pretrained(config.model.ernerf.asr_model).to(device)


    return {
        "scene": scene,
        "gaussians": gaussians,
        "gaussians_mouth": gaussians_mouth,
        "motion_net": motion_net,
        "motion_net_mouth": motion_net_mouth,
        "pipeline": pipeline,
        "background": background,
        "dilate": True,
        'audio_processor': audio_processor,
        'audio_model': audio_model
    }



def load_avatar(config):
    return None
    fullbody_list_cycle = None
    if config.model.talkinggaussian.fullbody:
        input_img_list = glob.glob(os.path.join(config.model.talkinggaussian.fullbody_img, '*.[jpJP][pnPN]*[gG]'))
        input_img_list = sorted(input_img_list, key=lambda x: int(os.path.splitext(os.path.basename(x))[0]))
        fullbody_list_cycle = read_imgs(input_img_list) #[:frame_total_num]
    return fullbody_list_cycle


class TalkingGaussianAvatar(BaseAvatar):
    """TalkingGaussian Avatar 實現，基於 Gaussian Splatting"""
    
    def __init__(self, config, model, avatar):
        """
        初始化 TalkingGaussian Avatar
        """
        super().__init__(config)
        
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        # Talking Gaussian
        self.gaussians = model['gaussians']
        self.gaussians_mouth = model['gaussians_mouth']
        self.motion_net = model['motion_net']
        self.motion_net_mouth = model['motion_net_mouth']
        self.background = model['background']
        self.pipeline = model['pipeline']
        self.scene = model['scene']
        self.dilate = model['dilate']
        
        # 獲取相機視角
        # self.cameras = self.scene.getTestCameras()
        self.cameras = self.scene.getTrainCameras()
        if len(self.cameras) == 0:
            self.cameras = self.scene.getTestCameras()
            
        logger.info(f'Available cameras: {len(self.cameras)}')
        
        self.current_camera_idx = 0
        
        # 配置引數
        self.W = config.video.width
        self.H = config.video.height
        
        # 初始化錄製所需的影片尺寸（繼承自 BaseAvatar）
        self.width = config.video.width
        self.height = config.video.height
        logger.info(f'[TalkingGaussian] 影片尺寸已初始化: {self.width}x{self.height}')
        
        # 建立音訊流處理器
        self.audio_processor = model['audio_processor']
        self.audio_model = model['audio_model']
        self.audio_stream = TalkingGaussianAudioStreamHandler(config, self, self.audio_processor, self.audio_model)
        self.audio_stream.warm_up()
        
        logger.info('TalkingGaussian Avatar initialized')
    
    def test_step(self, loop=None, audio_track=None, video_track=None):
        """
        單步推理和渲染（對齊 ERNeRF 的實現）
        每次呼叫渲染一幀
        """
        # 每次渲染對應 2 個音訊塊（25fps 影片, 50fps 音訊）
        audiotype1 = 0
        audiotype2 = 0
        
        for i in range(2):
            frame, type, eventpoint = self.audio_stream.get_audio_out()
            if i == 0:
                audiotype1 = type
            else:
                audiotype2 = type
            
            # 音訊推送到 WebRTC
            frame_int16 = (frame * 32767).astype(np.int16)
            new_frame = AudioFrame(format='s16', layout='mono', samples=frame_int16.shape[0])
            new_frame.planes[0].update(frame_int16.tobytes())
            new_frame.sample_rate = 16000
            asyncio.run_coroutine_threadsafe(audio_track._queue.put((new_frame, eventpoint)), loop)
            
            self.record_audio_data(frame_int16)
        
        if audiotype1 != 0 and audiotype2 != 0:  # 全為靜音資料
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
            # 進行推理渲染
            audio_feat = self.audio_stream.get_next_feat()  # [8, audio_dim, 16] for att_mode=2
            # logger.info(f'audio_feat shape: {audio_feat.shape}')
            
            camera_idx = self.mirror_index(len(self.cameras), self.current_camera_idx)
            camera = copy.deepcopy(self.cameras[camera_idx])
                
            if camera.original_image is None:
                camera = loadCamOnTheFly(camera, eval=True, bg_img_config=self.config.talkinggaussian.bg_img)
            
            camera.image_width = self.W
            camera.image_height = self.H
        
            # TalkingGaussian 從 camera.talking_dict 獲取音訊和表情特徵
            if not hasattr(camera, 'talking_dict'):
                camera.talking_dict = {}
            
            # 注入音訊特徵
            camera.talking_dict["auds"] = audio_feat.to(self.device)
            
            
            with torch.no_grad():
                # 渲染整體人臉
                render_pkg = render_motion(
                    camera, 
                    self.gaussians, 
                    self.motion_net, 
                    self.pipeline, 
                    self.background
                )
                
                # 渲染嘴部
                render_pkg_mouth = render_motion_mouth(
                    camera,
                    self.gaussians_mouth,
                    self.motion_net_mouth,
                    self.pipeline,
                    self.background
                )
            
            if self.dilate:
                alpha_mouth = dilate_fn(render_pkg_mouth["alpha"][None])[0]
            else:
                alpha_mouth = render_pkg_mouth["alpha"]
            
            mouth_image = render_pkg_mouth["render"] + camera.background.cuda() / 255.0 * (1.0 - alpha_mouth)
            
            alpha = render_pkg["alpha"]
            image = render_pkg["render"] + mouth_image * (1.0 - alpha)  # [3, H', W']
            
            # GPU 上 resize 到目標尺寸
            H, W = self.config.video.height, self.config.video.width
            if image.shape[1] != H or image.shape[2] != W:
                image = torch.nn.functional.interpolate(
                    image.unsqueeze(0),  # [1, 3, H', W']
                    size=(H, W),
                    mode='bilinear',
                    align_corners=False
                ).squeeze(0)  # [3, H, W]
            
            image = (image[0:3, ...].clamp(0, 1).permute(1, 2, 0).detach().cpu().numpy() * 255).astype(np.uint8)
            
            # 全身模式預留介面（當前未啟用）
            # if hasattr(self, 'fullbody_list_cycle') and len(self.fullbody_list_cycle) > 0:
            #     idx = self.current_camera_idx % len(self.fullbody_list_cycle)
            #     image_fullbody = self.fullbody_list_cycle[idx]
            #     image_fullbody = cv2.cvtColor(image_fullbody, cv2.COLOR_BGR2RGB)
            #     start_x = self.config.model.ernerf.fullbody_offset_x
            #     start_y = self.config.model.ernerf.fullbody_offset_y
            #     image_fullbody[start_y:start_y+image.shape[0], start_x:start_x+image.shape[1]] = image
            #     image = image_fullbody
            
            new_frame = VideoFrame.from_ndarray(image, format="rgb24")
            asyncio.run_coroutine_threadsafe(video_track._queue.put((new_frame, None)), loop)
            
            image_bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            self.record_video_data(image_bgr)
            
            self.current_camera_idx += 1
    
    def render(self, quit_event, loop=None, audio_track=None, video_track=None):
        """
        主渲染迴圈（模仿 ERNeRF）
        在主執行緒中同步執行音訊處理和渲染
        """
        self.init_customindex()
        
        count = 0
        totaltime = 0
        _starttime = time.perf_counter()
        _totalframe = 0
        
        # 啟動 TTS 執行緒
        self.tts.render(quit_event)
        
        while not quit_event.is_set():
            t = time.perf_counter()
            
            for _ in range(2):
                self.audio_stream.run_step()
            
            self.test_step(loop, audio_track, video_track)
            
            totaltime += (time.perf_counter() - t)
            count += 1
            _totalframe += 1
            
            if count == 100:
                logger.info(f"------actual avg infer fps:{count/totaltime:.4f}")
                count = 0
                totaltime = 0
            
            if video_track._queue.qsize() >= 5:
                time.sleep(0.04 * video_track._queue.qsize() * 0.8)
        
        logger.info('TalkingGaussian render thread stopped')
    
    def paste_back_frame(self, res_frame, idx):
        """
        TalkingGaussian 直接生成完整影像，不需要貼上
        """
        return res_frame
    
    def __del__(self):
        """清理資源"""
        logger.info(f'TalkingGaussianAvatar({self.sessionid}) deleted')

    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_value, traceback):
        self.audio_stream.stop()
