# Derived from Kedreamix/Linly-Talker-Stream.
# Copyright [Linly-talker-stream@kedreamix].
# Licensed under the Apache License, Version 2.0.
#
# Modified by HongXian0903, 2026.
# See LICENSE and NOTICE for details.
# Based on LiveTalking (C) 2024 LiveTalking@lipku https://github.com/lipku/LiveTalking (Apache-2.0).

"""WebRTC 相關路由"""
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
    """Negotiate media while preparing speech only for an incoming audio track."""
    if not getattr(state, "model_ready", False) or state.model is None or state.avatar is None:
        return web.json_response(
            {"code": -1, "msg": "請先在設定中選擇並套用數字人引擎與角色"}, status=409,
        )
    roles = getattr(state, "roles", None)
    if roles is not None and (roles.phase == "transition" or roles._apply_waiting):
        return web.json_response({"code": -1, "msg": "角色正在切換，請稍後連線"}, status=409)
    params = await request.json()
    client_role = str(params.get("client_role", "console")).strip().lower()
    if client_role not in {"console", "stage"}:
        client_role = "console"
    max_sessions = max(1, int(getattr(state.config.app, "max_session", 1)))
    if roles is not None and roles.enabled:
        max_sessions = 1
    if state.count_sessions(client_role) >= max_sessions:
        return web.json_response(
            {"code": -1, "msg": f"{client_role} WebRTC 會話數已達上限，請先關閉同類頁面"}, status=429,
        )
    description = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    sessionid = randN(6)
    while sessionid in state.avatar_streams:
        sessionid = randN(6)
    # Reserve before the first await so concurrent requests cannot overbook.
    state.add_session(sessionid, None, role=client_role)
    logger.info("WebRTC session %d (%s) reserved", sessionid, client_role)
    pc = voice_session = prepare_task = player = None
    cleaning = False

    async def cleanup():
        nonlocal cleaning
        if cleaning:
            return
        cleaning = True
        try:
            if prepare_task is not None:
                prepare_task.cancel()
                await asyncio.gather(prepare_task, return_exceptions=True)
            operations = []
            if voice_session is not None:
                operations.append(voice_session.close())
            if pc is not None:
                operations.append(pc.close())
            results = await asyncio.gather(*operations, return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException):
                    logger.warning("WebRTC cleanup failed type=%s", type(result).__name__)
            if player is not None:
                for track in (player.audio, player.video):
                    stop = getattr(track, "stop", None)
                    if callable(stop):
                        stop()
        finally:
            if pc is not None:
                state.remove_peer_connection(pc)
            state.remove_session(sessionid)
            from src.llm.service import remove_session as remove_llm_session
            remove_llm_session(sessionid)
            if roles is not None:
                roles.unregister(sessionid)

    try:
        # Shield the worker so a cancelled HTTP request can settle its resources
        # before releasing the role reservation.
        build = asyncio.create_task(asyncio.to_thread(
            create_avatar, roles.config_for_session() if roles else state.config,
            state.model, roles.data_for_session() if roles else state.avatar, sessionid,
        ))
        try:
            avatar_stream = await asyncio.shield(build)
        except asyncio.CancelledError:
            await build
            raise
        state.add_session(sessionid, avatar_stream, role=client_role)
        voice_session = VoiceTurnSession(
            sessionid, avatar_stream.config if roles and roles.enabled else state.config,
            avatar_stream, presenter=client_role,
            test_result_sink=state.voice_test_history.complete,
        )
        # No capture may start before an actual microphone track is prepared.
        voice_session._preparing = True
        state.voice_sessions[sessionid] = voice_session
        if roles is not None:
            roles.register(voice_session)
        ice_server = RTCIceServer(urls='stun:stun.miwifi.com:3478')
        pc = RTCPeerConnection(configuration=RTCConfiguration(iceServers=[ice_server]))
        state.add_peer_connection(pc)

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            logger.info("WebRTC session %d: %s", sessionid, pc.connectionState)
            if pc.connectionState in {"failed", "closed"}:
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
            nonlocal prepare_task
            if track.kind == "audio" and not cleaning:
                if prepare_task is None:
                    voice_session._preparing = True
                    prepare_task = asyncio.create_task(voice_session.prepare())
                voice_session.start_track(track)

        player = HumanPlayer(
            avatar_stream,
            on_audio_activity=voice_session.on_output_audio,
            on_audio_frame=voice_session.on_output_audio_frame,
            on_video_frame=voice_session.on_output_video_frame,
            on_media_timing=voice_session.observe_media_timing,
            on_audio_pacing=voice_session.observe_audio_pacing,
            media_guard=voice_session.accepts_media,
            on_stale_drop=voice_session.record_stale_drop,
        )
        voice_session.attach_media_player(player)
        pc.addTrack(player.audio)
        pc.addTrack(player.video)
        capabilities = RTCRtpSender.getCapabilities("video")
        preferences = [
            codec for name in ("H264", "VP8", "rtx")
            for codec in capabilities.codecs if codec.name == name
        ]
        video_transceiver = next(
            (item for item in pc.getTransceivers() if item.kind == "video"), None,
        )
        if video_transceiver is not None:
            video_transceiver.setCodecPreferences(preferences)
        await pc.setRemoteDescription(description)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        return web.json_response({
            "sdp": pc.localDescription.sdp, "type": pc.localDescription.type,
            "sessionid": sessionid,
        })
    except BaseException:
        await cleanup()
        raise
