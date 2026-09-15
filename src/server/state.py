# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""全域性狀態管理"""
from typing import Any, Dict, Set
from src.avatars.base import BaseAvatar
from aiortc import RTCPeerConnection
from src.server.voice_test_history import VoiceTestHistory


class ServerState:
    """伺服器全域性狀態管理類"""
    
    def __init__(self):
        # 會話管理
        self.avatar_streams: Dict[int, BaseAvatar] = {}  # sessionid -> BaseAvatar
        self.voice_sessions: Dict[int, Any] = {}
        self.voice_test_history = VoiceTestHistory()
        self.session_roles: Dict[int, str] = {}
        
        # WebRTC 連線管理
        self.pcs: Set[RTCPeerConnection] = set()
        
        # 配置和模型
        self.config = None
        self.config_path = None
        self.model = None
        self.avatar = None
        
        # 服務狀態
        self.server_ready = False
        self.model_ready = False
        self.switching = False
    
    def add_session(
        self,
        sessionid: int,
        avatar_stream: BaseAvatar = None,
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
    
    def get_session(self, sessionid: int) -> BaseAvatar:
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
