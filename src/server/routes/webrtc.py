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


async def close_sessions(*, presentation_change=False):
    """Close both presenters before an explicitly requested mode switch."""
    for session in list(state.voice_sessions.values()):
        if presentation_change:
            session._emit("presentation_changing")
    await asyncio.gather(*(cleanup() for cleanup in list(state.session_cleanups.values())))
    # Include peers created by older clients / integrations.
    await asyncio.gather(*(pc.close() for pc in list(state.pcs)))


async def release_session(request):
    params = await request.json()
    sessionid = params.get("sessionid")
    client_id = params.get("client_id")
    if not client_id or state.session_clients.get(sessionid) != client_id:
        return web.json_response({"code": -1, "msg": "無效的連線識別"}, status=403)
    cleanup = state.session_cleanups.get(sessionid)
    if cleanup:
        await cleanup()
    return web.json_response({"code": 0})


async def offer(request):
    """Reserve one slot per presenter; unwind every failed negotiation."""
    from src.avatars.presentation import mode, snapshot
    if not getattr(state, "reply_prewarm_ready", True):
        return web.json_response({"code": -1, "msg": "正在準備對話，請稍後再連線"}, status=503)
    if state.switching:
        return web.json_response({"code": -1, "msg": "正在製作或切換數位人，請稍候"}, status=409)
    if not state.model_ready or (state.model is None and mode(state.config) != "prerecorded") or state.avatar is None:
        return web.json_response({"code": -1, "msg": "請先在設定中選擇並套用數字人引擎與角色"}, status=409)
    params = await request.json()
    client_role = str(params.get("client_role", "console")).strip().lower()
    if client_role not in {"console", "stage"}:
        client_role = "console"
    client_id = str(params.get("client_id") or "")[:128]
    if client_id:
        for existing in list(state.avatar_streams):
            if state.session_clients.get(existing) == client_id and state.session_roles.get(existing) == client_role:
                cleanup = state.session_cleanups.get(existing)
                if cleanup:
                    await cleanup()
    if state.switching:
        return web.json_response({"code": -1, "msg": "正在製作或切換數位人，請稍候"}, status=409)
    max_sessions = max(1, int(getattr(state.config.app, "max_session", 1)))
    if state.count_sessions(client_role) >= max_sessions:
        return web.json_response({"code": -1, "msg": f"{client_role} WebRTC 會話數已達上限，請先關閉同類頁面"}, status=429)
    description = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    sessionid = randN(6)
    while sessionid in state.avatar_streams:
        sessionid = randN(6)
    # No await between capacity check and reservation.
    state.add_session(sessionid, None, role=client_role)
    state.session_clients[sessionid] = client_id
    logger.info("WebRTC session %d (%s) reserved", sessionid, client_role)
    pc = voice_session = prepare_task = None
    cleaning = False
    disconnect_timer = None

    async def cleanup():
        nonlocal cleaning
        if cleaning:
            return
        cleaning = True
        if disconnect_timer:
            disconnect_timer.cancel()
        try:
            if voice_session is not None:
                await voice_session.close()
        finally:
            if prepare_task is not None and not prepare_task.done():
                prepare_task.cancel()
            try:
                if pc is not None:
                    await pc.close()
            finally:
                if pc is not None:
                    state.remove_peer_connection(pc)
                state.remove_session(sessionid)

    try:
        # A cancelled HTTP request must still wait for avatar construction to
        # finish before it releases the slot / exclusive model workspace.
        creating = asyncio.create_task(asyncio.to_thread(
            create_avatar, state.config, state.model, state.avatar, sessionid))
        try:
            avatar_stream = await asyncio.shield(creating)
        except asyncio.CancelledError:
            await creating
            raise
        state.add_session(sessionid, avatar_stream, role=client_role)
        voice_session = VoiceTurnSession(sessionid, state.config, avatar_stream,
                                        presenter=client_role, test_result_sink=state.voice_test_history.complete)
        state.voice_sessions[sessionid] = voice_session
        # LAN clients need host candidates only. External STUN is opt-in and
        # must not add a DNS/network timeout to every local connection.
        ice_servers = []
        stun = params.get("stun_server")
        if isinstance(stun, str) and stun.startswith(("stun:", "stuns:")):
            ice_servers.append(RTCIceServer(urls=stun))
        pc = RTCPeerConnection(configuration=RTCConfiguration(iceServers=ice_servers))
        state.add_peer_connection(pc)
        state.session_cleanups[sessionid] = cleanup

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            nonlocal disconnect_timer
            logger.info("WebRTC session %d (%s): %s", sessionid, client_role, pc.connectionState)
            if pc.connectionState in {"failed", "closed"}:
                await cleanup()
            elif pc.connectionState == "disconnected":
                if disconnect_timer:
                    disconnect_timer.cancel()
                disconnect_timer = asyncio.get_running_loop().call_later(
                    3, lambda: asyncio.create_task(cleanup()))
            elif pc.connectionState == "connected" and disconnect_timer:
                disconnect_timer.cancel()

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
                asyncio.create_task(cleanup())
            if channel.readyState == "open":
                attach_voice_events()

        @pc.on("track")
        def on_track(track):
            nonlocal prepare_task
            if track.kind == "audio":
                # Prepare speech in parallel with ICE; the microphone gate
                # remains shut until preparation actually succeeds.
                voice_session._preparing = True
                prepare_task = asyncio.create_task(voice_session.prepare())
                voice_session.start_track(track)

        player = HumanPlayer(avatar_stream,
            on_audio_activity=voice_session.on_output_audio,
            on_audio_frame=voice_session.on_output_audio_frame,
            on_audio_clock=voice_session.on_output_audio_clock,
            on_media_timing=voice_session.observe_media_timing,
            on_audio_pacing=voice_session.observe_audio_pacing,
            media_guard=voice_session.accepts_media,
            on_stale_drop=voice_session.record_stale_drop)
        voice_session.attach_media_player(player)
        pc.addTrack(player.audio)
        pc.addTrack(player.video)
        capabilities = RTCRtpSender.getCapabilities("video")
        preferences = [c for name in ("H264", "VP8", "rtx") for c in capabilities.codecs if c.name == name]
        video_transceiver = next((item for item in pc.getTransceivers() if item.kind == "video"), None)
        if video_transceiver is not None:
            video_transceiver.setCodecPreferences(preferences)
        await pc.setRemoteDescription(description)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        return web.json_response({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type,
            "sessionid": sessionid,
            "presentation": snapshot(state.config) if mode(state.config) == "prerecorded" else {"mode": "musetalk"}})
    except BaseException:
        await cleanup()
        raise
