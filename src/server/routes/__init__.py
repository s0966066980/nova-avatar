"""路由模組"""
from .webrtc import offer
from .chat import human, interrupt_talk, is_speaking, clear_history
from .audio import humanaudio, asr
from .video import set_audiotype, record, download_record
from .health import health_check
from .settings import (
    get_settings,
    get_vad_settings,
    set_vad_settings,
    get_speech_settings,
    set_stt_settings,
    set_tts_settings,
    pick_speech_path,
    get_stage_settings,
    set_stage_settings,
    list_llm_models,
    set_llm_model,
    get_llm_rules,
    set_llm_rules,
    set_avatar,
    set_mouth_quality,
    avatar_preview,
    import_avatar,
    import_avatar_status,
)

__all__ = [
    'offer',
    'human',
    'interrupt_talk', 
    'is_speaking',
    'clear_history',
    'humanaudio',
    'asr',
    'set_audiotype',
    'record',
    'download_record',
    'health_check',
    'get_settings',
    'get_vad_settings',
    'set_vad_settings',
    'get_speech_settings',
    'set_stt_settings',
    'set_tts_settings',
    'pick_speech_path',
    'get_stage_settings',
    'set_stage_settings',
    'list_llm_models',
    'set_llm_model',
    'get_llm_rules',
    'set_llm_rules',
    'set_avatar',
    'set_mouth_quality',
    'avatar_preview',
    'import_avatar',
    'import_avatar_status',
]
