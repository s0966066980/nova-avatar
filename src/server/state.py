# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""全域性狀態管理"""
from typing import TYPE_CHECKING, Any, Dict, Optional, Set
from aiortc import RTCPeerConnection
from src.server.voice_test_history import VoiceTestHistory

if TYPE_CHECKING:
    from nova_contracts.stt import SttService
    from nova_contracts.tts import TtsRuntime, TtsService
    from src.server.speaking_avatar import SpeakingAvatar


class ServerState:
    """伺服器全域性狀態管理類"""
    
    def __init__(self):
        # 會話管理
        self.avatar_streams: Dict[int, "SpeakingAvatar"] = {}  # sessionid -> renderer + TTS
        self.voice_sessions: Dict[int, Any] = {}
        self.voice_test_history = VoiceTestHistory()
        self.session_roles: Dict[int, str] = {}
        self.presentation = None
        
        # WebRTC 連線管理
        self.pcs: Set[RTCPeerConnection] = set()
        
        # 配置和模型
        self.config = None
        self.config_path = None
        self.model = None
        self.avatar = None
        self.roles = None
        # The STT layer's service, shared by every voice session and /asr.
        self.stt: Optional["SttService"] = None
        # The TTS layer's service and, in-process, its runtime (speech channels,
        # startup and shutdown); app.py sets both to the same adapter.
        self.tts: Optional["TtsService"] = None
        self.tts_runtime: Optional["TtsRuntime"] = None
        
        # 服務狀態
        self.server_ready = False
        self.prewarm_status = {}
        self.model_ready = False
        self.switching = False
        self.settings_applying = False
        self.shutting_down = False
    
    def add_session(
        self,
        sessionid: int,
        avatar_stream: "SpeakingAvatar" = None,
        role: str = "console",
    ):
        """新增會話"""
        self.avatar_streams[sessionid] = avatar_stream
        self.session_roles[sessionid] = role
    
    def remove_session(self, sessionid: int):
        """移除會話"""
        if sessionid in self.avatar_streams:
            del self.avatar_streams[sessionid]
        self.voice_sessions.pop(sessionid, None)
        self.session_roles.pop(sessionid, None)

    def count_sessions(self, role: str) -> int:
        """計算指定頁面角色的會話；舊會話預設視為控制台。"""
        return sum(
            1
            for sessionid in self.avatar_streams
            if self.session_roles.get(sessionid, "console") == role
        )
    
    def get_session(self, sessionid: int) -> "SpeakingAvatar":
        """獲取會話"""
        return self.avatar_streams.get(sessionid)
    
    def add_peer_connection(self, pc: RTCPeerConnection):
        """新增 WebRTC 連線"""
        self.pcs.add(pc)
    
    def remove_peer_connection(self, pc: RTCPeerConnection):
        """移除 WebRTC 連線"""
        self.pcs.discard(pc)


# 全域性狀態例項
state = ServerState()
