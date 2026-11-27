# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""預設配置值"""
from .schema import Config, AppConfig, ModelConfig, TTSConfig, LLMConfig, AudioConfig, VideoConfig, CustomVideoConfig


def get_default_config() -> Config:
    """
    獲取預設配置
    
    Returns:
        Config: 預設配置物件
    """
    return Config(
        app=AppConfig(
            listenport=8010,
            max_session=1
        ),
        model=ModelConfig(
            type="musetalk",
            avatar_id="avator_1",
            batch_size=16,
            model_path="./models"
        ),
        tts=TTSConfig(
            type="edgetts",
            ref_file="zh-CN-YunxiaNeural",
            ref_text=None,
            tts_server="http://127.0.0.1:9880"
        ),
        llm=LLMConfig(
            api_key="",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen-plus"
        ),
        audio=AudioConfig(
            fps=50,
            sample_rate=16000,
            l=10,
            m=8,
            r=10,
            av_offset_ms=0
        ),
        video=VideoConfig(
            width=450,
            height=450,
            fps=25
        ),
        custom_video=CustomVideoConfig(
            config_path=""
        )
    )
