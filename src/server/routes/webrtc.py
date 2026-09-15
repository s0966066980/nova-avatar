# Derived from Kedreamix/Linly-Talker-Stream.
# Copyright [Linly-talker-stream@kedreamix].
# Licensed under the Apache License, Version 2.0.
#
# Modified by HongXian0903, 2026.
# See LICENSE and NOTICE for details.
# Based on LiveTalking (C) 2024 LiveTalking@lipku https://github.com/lipku/LiveTalking (Apache-2.0).

"""WebRTC 相關路由"""
import json
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceServer, RTCConfiguration
from aiortc.rtcrtpsender import RTCRtpSender
import asyncio

from src.utils.webrtc import HumanPlayer
from src.avatars.factory import create_avatar
from src.utils.logging import logger
from src.server.state import state
from src.server.utils import randN
from src.server.voice_session import VoiceTurnSession


async def offer(request):
    """處理 WebRTC offer 請求"""
    if not getattr(state, "model_ready", False) or state.model is None or state.avatar is None:
        return web.Response(
            status=409,
            content_type="application/json",
            text=json.dumps(
                {"code": -1, "msg": "請先在設定中選擇並套用數字人引擎與角色"}
            ),
        )

    params = await request.json()
    client_role = str(params.get("client_role", "console")).strip().lower()
    if client_role not in {"console", "stage"}:
        client_role = "console"

    max_sessions = max(1, int(getattr(state.config.app, "max_session", 1)))
    if state.count_sessions(client_role) >= max_sessions:
        return web.Response(
            status=429,
            content_type="application/json",
            text=json.dumps(
                {
                    "code": -1,
                    "msg": f"{client_role} WebRTC 會話數已達上限，請先關閉同類頁面",
                }
            ),
        )

    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    # No await between this second check and reservation: concurrent offers
    # cannot both pass max_session while avatar creation is in an executor.
    if state.count_sessions(client_role) >= max_sessions:
        return web.Response(
            status=429,
            content_type="application/json",
            text=json.dumps(
                {
                    "code": -1,
                    "msg": f"{client_role} WebRTC 會話數已達上限，請稍後再試",
                }
            ),
        )
    sessionid = randN(6)
    state.add_session(sessionid, None, role=client_role)
    logger.info(
        'sessionid=%d, role=%s, role sessions=%d, total sessions=%d',
        sessionid,
        client_role,
        state.count_sessions(client_role),
        len(state.avatar_streams),
    )
    
    # 建立 avatar 可能耗時，放執行緒池
    avatar_stream = await asyncio.get_event_loop().run_in_executor(
        None, create_avatar, state.config, state.model, state.avatar, sessionid
    )
    state.add_session(sessionid, avatar_stream, role=client_role)

    voice_session = VoiceTurnSession(
        sessionid,
        state.config,
        avatar_stream,
        presenter=client_role,
    )
    state.voice_sessions[sessionid] = voice_session
    # This is intentionally before "listening": Silero and STT failures degrade
    # the session to text without ever opening the microphone gate.
    await voice_session.prepare()
    
    ice_server = RTCIceServer(urls='stun:stun.miwifi.com:3478')
    pc = RTCPeerConnection(configuration=RTCConfiguration(iceServers=[ice_server]))
    state.add_peer_connection(pc)

    async def cleanup():
        session = state.voice_sessions.get(sessionid)
        if session is not None:
            await session.close()
        state.remove_peer_connection(pc)
        state.remove_session(sessionid)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        logger.info("Connection state is %s" % pc.connectionState)
        if pc.connectionState == "failed":
            await pc.close()
            await cleanup()
        elif pc.connectionState == "closed":
            await cleanup()

    @pc.on("datachannel")
    def on_datachannel(channel):
        if channel.label != "voice-events":
            return

        def attach_voice_events():
            voice_session.attach_event_sink(channel.send)

        @channel.on("open")
        def on_open():
            attach_voice_events()

        @channel.on("message")
        def on_message(message):
            if isinstance(message, str):
                voice_session.handle_control(message)

        @channel.on("close")
        def on_close():
            voice_session.detach_event_sink()

        if channel.readyState == "open":
            attach_voice_events()

    @pc.on("track")
    def on_track(track):
        if track.kind == "audio":
            voice_session.start_track(track)

    player = HumanPlayer(
        state.avatar_streams[sessionid],
        on_audio_activity=voice_session.on_output_audio,
        on_audio_frame=voice_session.on_output_audio_frame,
        on_media_timing=voice_session.observe_media_timing,
        on_audio_pacing=voice_session.observe_audio_pacing,
        media_guard=voice_session.accepts_media,
        on_stale_drop=voice_session.record_stale_drop,
    )
    voice_session.attach_media_player(player)
    pc.addTrack(player.audio)
    pc.addTrack(player.video)
    
    capabilities = RTCRtpSender.getCapabilities("video")
    preferences = list(filter(lambda x: x.name == "H264", capabilities.codecs))
    preferences += list(filter(lambda x: x.name == "VP8", capabilities.codecs))
    preferences += list(filter(lambda x: x.name == "rtx", capabilities.codecs))
    video_transceiver = next(
        (item for item in pc.getTransceivers() if item.kind == "video"),
        None,
    )
    if video_transceiver is not None:
        video_transceiver.setCodecPreferences(preferences)

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "sessionid": sessionid}
        ),
    )
