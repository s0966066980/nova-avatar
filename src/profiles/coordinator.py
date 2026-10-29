# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Shared role defaults and an independent role coordinator per conversation."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from functools import partial
from pathlib import Path
import time
from uuid import uuid4

from src.avatars.factory import load_avatar_data
from src.llm.service import select_session_profile, session_history
from src.profiles.media import RolePresentation, TransitionMedia, _VideoReader
from src.profiles.routing import RoutingClients, route_question
from src.greetings.content import validate_content
from src.profiles.store import RETURN_ANNOUNCEMENTS, ProfileError, ProfileStore, compatible_pair, profile_config
from src.profiles.weather import CwaWeather, WeatherQuery
from src.utils.logging import logger

# The plan of a turn the current main role answers itself. It is also the
# plan a concurrently started main answer assumes before routing decides.
ANSWER_CONTEXT = "本輪未取得即時氣象資料，不可提供實際即時天氣數值。"


async def _bind_avatar(avatar, config, data):
    # Cancellation must settle the worker before cleanup releases the avatar.
    task = asyncio.create_task(asyncio.to_thread(avatar.bind_profile, config, data))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


class ConversationRoles:
    """One conversation owns its current role, transition and pending handoff."""

    def __init__(self, manager, voice):
        self.manager, self.voice = manager, voice
        self.base_config = deepcopy(voice.config)
        self.library = deepcopy(getattr(voice.config, "role_library_snapshot", manager.library))
        self.assets = manager.assets
        self.router, self.weather, self.media = manager.router, manager.weather, manager.media
        self.current_id = self.library["pair"]["main"]
        self.phase = "ready" if manager.enabled else "disabled"
        self.error = ""
        self.profiles_applied = manager.profiles_applied
        self.pending, self.continuations, self.confirmed = {}, {}, {}
        self._lock = asyncio.Lock()
        self._transition_event = None
        self._transition_id = ""
        self._transition_owner = None

    @property
    def enabled(self):
        return bool(self.library["enabled"] and self.phase != "disabled")

    @property
    def profiles(self):
        return {p["id"]: p for p in self.library["profiles"]}

    def snapshot(self):
        return dict(enabled=self.enabled, phase=self.phase,
                    sessionid=self.voice.sessionid,
                    active_profile_id=self.current_id, pair=self.library["pair"],
                    active_revision=self.library["revision"], error=self.error,
                    weather_configured=self.weather.configured,
                    profiles_applied=self.profiles_applied,
                    active_avatar_id=self.profiles[self.current_id]["avatar_id"]
                        if self.profiles_applied or self.enabled else "",
                    can_return=self.enabled and self.current_id == self.library["pair"]["specialist"]
                               and self.phase == "ready", applying=False)

    def notify(self, session=None):
        self.voice._emit("role_state", **self.snapshot())
        self.voice._refresh_gate()

    def input_allowed(self, session):
        return session is self.voice and self.phase in {"ready", "announcement", "disabled"}

    def all_idle(self):
        return self.voice._is_conversation_idle()

    def _bind(self, voice, profile_id):
        profile = self.profiles[profile_id]
        config = profile_config(self.base_config, profile)
        config.conversation_snapshot = True
        voice.avatar.bind_profile(config, self.assets[profile["avatar_id"]])
        self._finish_binding(voice, profile_id)

    async def _bind_async(self, voice, profile_id):
        profile = self.profiles[profile_id]
        config = profile_config(self.base_config, profile)
        config.conversation_snapshot = True
        # Building per-avatar continuity controllers touches many frames. Keep
        # RTP pacing on the event loop while the asset lock fences the renderer.
        await _bind_avatar(voice.avatar, config, self.assets[profile["avatar_id"]])
        self._finish_binding(voice, profile_id)

    def _finish_binding(self, voice, profile_id):
        voice.config = voice.avatar.config
        if hasattr(voice, "bind_conversation"):
            voice.bind_conversation()
        voice._turn_context = None
        select_session_profile(voice.sessionid, profile_id)
        if getattr(voice.avatar, "_role_presentation", None) is None:
            voice.avatar._role_presentation = RolePresentation()
        if voice._media_player is not None:
            voice._media_player.discard_stale_media()

    def continues(self, voice, turn_id):
        """True when this turn answers a handoff; its plan needs no routing."""
        continuation = self.continuations.get(voice.sessionid)
        return bool(continuation
                    and continuation.get('target_profile_id') == self.current_id
                    and continuation.get('target_turn') == turn_id)

    def speculative_plan(self):
        """The plan of a turn routing keeps with the current role, adding no facts.

        A main answer started before routing decides uses this plan; a routed
        plan equal to it releases that answer, any other plan replaces it.
        """
        if self.current_id == self.library["pair"]["main"]:
            return {"context": ANSWER_CONTEXT}
        return {"weather": None, "context": ""}

    async def before_generate(self, voice, text, turn_id, generation):
        if not self.enabled:
            return None
        sid = voice.sessionid
        continuation = self.continuations.get(sid)
        if continuation:
            if (continuation.get('target_profile_id') != self.current_id
                    or continuation.get('target_turn') != turn_id):
                self.cancel(sid)
            else:
                self.continuations.pop(sid)
                result = await continuation["weather_task"] if continuation.get("weather_task") else None
                return {"weather": result, "context": continuation.get("context", "")}
        if not self.input_allowed(voice):
            return {"cancelled": True}
        self.error = ""
        self.notify(voice)
        try:
            route = await asyncio.to_thread(
                self.router, voice.config, self.library, self.current_id, text,
                session_history(sid), self.confirmed.get(sid, {}))
        except asyncio.CancelledError:
            raise
        except Exception:
            return {"fixed": "目前無法確認問題的接手方式，請再說一次您的問題。"}
        if not voice._is_current(turn_id, generation):
            return {"cancelled": True}
        if route["route"] == "clarify":
            return {"fixed": route.get("clarification") or "請問您想先詢問哪個主題？"}
        specialist_id = self.library["pair"]["specialist"]
        target_id = specialist_id if route['route'] == 'specialist' else self.library['pair']['main']
        if target_id == self.current_id and route['route'] == 'answer':
            return {"context": ANSWER_CONTEXT}
        target = self.profiles[target_id]
        if getattr(voice, 'attachments', None) and voice.attachments.selection:
            from src.server.attachments import vision_ready
            target_config = profile_config(self.base_config, target)
            if not await asyncio.to_thread(vision_ready, target_config):
                voice._emit('attachment_status', state='error', error='handoff_vision_unavailable')
                return {'fixed': ('This role cannot read the attachments. Please deselect them or ask an administrator to select a compatible model.'
                    if voice._conversation['locale'] == 'en-US' else '接手角色目前無法讀取附件，請取消勾選附件，或由管理者套用相容模型後重試。')}
            if not voice._is_current(turn_id, generation):
                return {'cancelled': True}
        weather_task = None
        if route['route'] == 'specialist' and target["tools"]["weather"]:
            if not route.get("county"):
                return {"fixed": "請問您想查詢哪個縣市的天氣？"}
            town = route.get("town", "")
            self.confirmed[sid] = {"county": route["county"], "town": town}
            weather_query = WeatherQuery(route["county"], town, route["kind"],
                                         route["start_date"], route["end_date"], route.get("accepted_at", ""))
            weather_task = asyncio.create_task(self.weather.query(weather_query))
        if self.current_id == target_id:
            result = await weather_task if weather_task else None
            return {"weather": result, "context": route.get("context", "")}
        pending = dict(id=uuid4().hex, question=text, source_turn=turn_id,
                       target_profile_id=target_id,
                       generation=generation, weather_task=weather_task,
                       context=route.get("context", ""), readers={})
        self.pending[sid] = pending
        try:
            edge = self.edge(self.current_id, target_id)
            if edge["kind"] == "video":
                info, path = self.media.get(edge["asset_id"])
                for other in (self.voice,):
                    pending["readers"][other.sessionid] = await asyncio.to_thread(
                        _VideoReader, path, info["frames"])
        except asyncio.CancelledError:
            self.cancel(sid)
            raise
        except Exception:
            # A clip failure has a specified built-in fallback.
            for reader in pending["readers"].values():
                reader.close()
            pending["readers"] = {}
        if not voice._is_current(turn_id, generation):
            self.cancel(sid)
            return {"cancelled": True}
        self.phase = "announcement"
        self.notify()
        reverse = target_id == self.library['pair']['main']
        key = 'return_announcement' if reverse else 'announcement'
        if voice._conversation['locale'] == 'en-US':
            key += '_en'
        announcement = self.library['handoff'].get(key, '')
        if not announcement:
            announcement = RETURN_ANNOUNCEMENTS[key] if reverse else (
                'I will ask our specialist to help with your question.' if voice._conversation['locale'] == 'en-US'
                else '接下來請專門數位人接續回答您的問題。')
        return {"fixed": announcement, "handoff_id": pending["id"]}

    def edge(self, source, target):
        return next((dict(e) for e in self.library["transitions"]
                     if e["source"] == source and e["target"] == target),
                    dict(source=source, target=target, kind="effect", effect="fade", duration=.6))

    def cancel(self, sid):
        pending = self.pending.pop(sid, None)
        continuation = self.continuations.pop(sid, None)
        for item in (pending, continuation):
            if item:
                task = item.get("weather_task")
                if task and not task.done():
                    task.cancel()
                for reader in item.get("readers", {}).values():
                    reader.close()
        if pending and self.phase == "announcement":
            self.phase = "ready"
            self.notify()

    async def after_playback(self, voice, completed_turn):
        pending = self.pending.get(voice.sessionid)
        if not pending or pending["source_turn"] != completed_turn:
            return
        try:
            await self._switch(pending['target_profile_id'], voice,
                               transition_id=pending["id"], readers=pending["readers"])
            if self.pending.pop(voice.sessionid, None) is not pending:
                return
            pending["readers"] = {}
            self.continuations[voice.sessionid] = pending
            result = await voice.start_text_turn(pending["question"], interrupt=False,
                                                 _handoff_id=pending["id"])
            voice._emit("role_handoff", handoff_id=pending["id"],
                        source_turn_id=completed_turn, target_turn_id=result["turn_id"])
        except asyncio.CancelledError:
            if (self.pending.get(voice.sessionid) is pending
                    or self.continuations.get(voice.sessionid) is pending):
                self.cancel(voice.sessionid)
            raise
        except Exception:
            if (self.pending.get(voice.sessionid) is not pending
                    and self.continuations.get(voice.sessionid) is not pending):
                return
            self.cancel(voice.sessionid)
            self.error = "角色交接暫時無法完成，請再試一次"
            self.phase = "ready"
            self.notify()

    def video_committed(self, sid, eventpoint):
        if (isinstance(eventpoint, dict) and sid == self._transition_owner
                and eventpoint.get("role_transition_id") == self._transition_id
                and eventpoint.get("role_transition_end") and self._transition_event is not None):
            self._transition_event.set()

    async def _switch(self, target, owner, *, transition_id=None, readers=None):
        if self.phase == "transition" or self._lock.locked():
            raise ProfileError("角色正在轉場，請稍候", 409)
        async with self._lock:
            for voice in (self.voice,):
                if hasattr(voice, "greetings") and not voice._greeting_returning:
                    voice.greetings.reset(stop_playing=True)
            source = self.current_id
            if source == target:
                return
            requested_at = time.monotonic()
            edge = self.edge(source, target)
            readers = readers or {}
            transition_id = transition_id or uuid4().hex
            self.phase = "transition"
            self._transition_id, self._transition_owner = transition_id, owner.sessionid
            self._transition_event = asyncio.Event()
            self.notify()
            try:
                voices = (self.voice,)
                prepared = []
                for voice in voices:
                    requested, paused = voice._capture_requested, voice._manual_pause
                    if not voice._is_conversation_idle():
                        await voice.interrupt()
                    else:
                        voice._generation += 1
                    voice._capture_requested, voice._manual_pause = requested, paused
                    voice._emit("board_clear")
                    voice._emit("role_clear")
                    reader = readers.get(voice.sessionid)
                    if reader is None and edge["kind"] == "video":
                        try:
                            info, path = self.media.get(edge["asset_id"])
                            reader = await asyncio.to_thread(_VideoReader, path, info["frames"])
                        except Exception:
                            reader = None
                    if reader:
                        readers[voice.sessionid] = reader
                    actual_edge = edge if edge["kind"] != "video" or reader else {
                        "kind": "effect", "effect": "fade", "duration": .6}
                    presentation = voice.avatar._role_presentation
                    presentation.begin(transition_id, actual_edge, reader=reader,
                                       started_at=time.monotonic() + 3600)
                    prepared.append((voice, presentation))
                for voice, _ in prepared:
                    await self._bind_async(voice, target)
                started = time.monotonic()
                for _, presentation in prepared:
                    with presentation.lock:
                        presentation.transition["started"] = started
                duration = max((r.frames / 25 for r in readers.values()), default=edge.get("duration", .6))
                for voice, _ in prepared:
                    voice._emit("role_transition_started", transition_id=transition_id,
                        source_profile_id=source, target_profile_id=target,
                        preparation_seconds=started-requested_at, duration_seconds=duration)
                if owner._media_player is not None:
                    await asyncio.wait_for(self._transition_event.wait(), timeout=max(2.6, duration + 3))
                else:
                    await asyncio.sleep(duration)
                self.current_id = target
                for voice, _ in prepared:
                    voice._emit("role_transition_completed", transition_id=transition_id,
                        elapsed_seconds=time.monotonic()-started)
            except BaseException:
                for voice in (self.voice,):
                    await self._bind_async(voice, source)
                raise
            finally:
                for voice in (self.voice,):
                    presentation = getattr(voice.avatar, "_role_presentation", None)
                    if presentation:
                        presentation.close()
                self.phase = "ready"
                self._transition_event = None
                self.notify()

    async def return_to_main(self, requester):
        if not self.enabled or self.current_id == self.library["pair"]["main"]:
            return self.snapshot()
        owner = requester
        try:
            await self._switch(self.library["pair"]["main"], owner)
        except asyncio.CancelledError:
            raise
        except ProfileError:
            raise
        except Exception as exc:
            self.error = "目前無法返回主數位人，請稍後再試"
            self.notify()
            raise ProfileError(self.error, 503) from exc
        return self.snapshot()

    def visitor_reset(self, voice):
        self.confirmed.pop(voice.sessionid, None)
        self.cancel(voice.sessionid)
        voice._greeting_returning = True
        self.phase = "resetting"
        self.notify()
        async def restart():
            try:
                await self.manager.restart_conversation(voice, self)
            except Exception:
                self.error = "新對話設定尚未就緒，請重新連線"
                self.phase = "ready" if self.library["enabled"] else "disabled"
                self.notify()
                logger.exception("Conversation settings could not be refreshed")
            finally:
                voice._greeting_returning = False
                voice._refresh_gate()
        voice._role_reset_task = asyncio.create_task(restart())

    async def close(self):
        for sid in list(self.pending):
            self.cancel(sid)
        presentation = getattr(self.voice.avatar, "_role_presentation", None)
        if presentation:
            presentation.close()


class RoleCoordinator:
    """Publish defaults without mutating any connected conversation."""

    def __init__(self, state, store, library, *, loader=load_avatar_data,
                 router=None, routing_clients=None, weather=None, media=None):
        self.state, self.store = state, store
        self.library = deepcopy(library)
        self.loader = loader
        # Every turn routes through the same pooled clients; worker threads
        # may route concurrently, and close() releases them on shutdown.
        self.routing_clients = routing_clients or RoutingClients()
        self.router = router or partial(route_question, clients=self.routing_clients)
        self.weather = weather or CwaWeather()
        self.media = media or TransitionMedia()
        self.assets, self.sessions = {}, {}
        self.profiles_applied = False
        self.phase, self.error = "disabled", ""
        self._apply_waiting = False
        self._pending_library = None

    @property
    def enabled(self):
        return bool(self.library["enabled"] and self.phase != "disabled")

    @property
    def profiles(self):
        return {p["id"]: p for p in self.library["profiles"]}

    @property
    def current_id(self):
        return self.library["pair"]["main"]

    def snapshot(self):
        return dict(enabled=self.enabled, phase=self.phase,
                    active_profile_id=self.current_id, pair=self.library["pair"],
                    active_revision=self.library["revision"], error=self.error,
                    weather_configured=self.weather.configured,
                    profiles_applied=self.profiles_applied,
                    active_avatar_id=self.profiles[self.current_id]["avatar_id"]
                        if self.profiles_applied else "",
                    can_return=False, applying=self._apply_waiting,
                    pending=self._pending_library is not None,
                    pending_revision=(self._pending_library or {}).get("revision"))

    def notify(self, session=None):
        for roles in list(self.sessions.values()):
            if session is None or roles.voice is session:
                roles.notify()

    def input_allowed(self, voice):
        roles = self.sessions.get(voice.sessionid)
        return roles.input_allowed(voice) if roles else not self._apply_waiting

    @staticmethod
    def _resource_key(config):
        llm = config.llm
        return (config.model.type, config.tts.type, llm.provider, llm.model,
                llm.base_url, llm.llamacpp_ctx, llm.llamacpp_host, llm.llamacpp_port)

    async def apply(self, library=None, *, startup=False):
        if self._apply_waiting or getattr(self.state, "switching", False) or getattr(self.state, "settings_applying", False):
            raise ProfileError("設定正在套用，請稍候", 409)
        target = deepcopy(library or self.store.load())
        profiles = {p["id"]: p for p in target["profiles"]}
        main = profiles[target["pair"]["main"]]
        if self.state.config.stage.idle_greeting_enabled:
            try:
                validate_content(main.get("greeting"), required=True)
            except ValueError as exc:
                raise ProfileError(str(exc)) from exc
        selected = [main]
        if target["enabled"]:
            selected = list(compatible_pair(target))
        config = profile_config(self.state.config, main)
        # A local model server or shared renderer cannot be replaced underneath
        # another conversation. Keep the saved library pending until disconnect.
        if any(v is None for v in self.state.avatar_streams.values()) or self.state.avatar_streams and any(
                self._resource_key(config) != self._resource_key(v.config)
                or (not hasattr(v.avatar, "bind_profile") and config.model.avatar_id != v.config.model.avatar_id)
                for v in self.state.voice_sessions.values()):
            self._pending_library = target
            return self.snapshot()
        self._apply_waiting = True
        try:
            if config.model.type != self.state.config.model.type:
                from src.server.runtime_settings import apply_avatar
                await asyncio.to_thread(apply_avatar, self.state.config,
                    main["engine"], main["avatar_id"], session_count=0)
                self.assets = {}
            if config.tts.type != self.state.config.tts.type:
                from src.server.runtime_settings import apply_tts_settings
                await asyncio.to_thread(apply_tts_settings, self.state.config,
                    main["tts"], session_count=0)
            config = profile_config(self.state.config, main)
            cache = {}
            for profile in selected:
                aid = profile["avatar_id"]
                from src.avatars.catalog import avatar_bootable, avatar_uses_green_screen
                valid, reason = avatar_bootable(profile["engine"], aid)
                if not valid:
                    raise ProfileError(reason, 409)
                if target["enabled"] and not avatar_uses_green_screen(aid):
                    raise ProfileError("人物層轉場需要綠幕 MuseTalk 素材", 409)
                if aid in self.assets:
                    cache[aid] = self.assets[aid]
                elif aid == self.state.config.model.avatar_id and self.state.avatar is not None:
                    cache[aid] = self.state.avatar
                else:
                    cache[aid] = await asyncio.to_thread(self.loader, profile_config(self.state.config, profile))
            for edge in target["transitions"]:
                if edge["kind"] == "video":
                    self.media.get(edge["asset_id"])
            if config.llm.provider == "llamacpp" and not self.state.avatar_streams:
                from src.llm.llamacpp import ensure_server
                # The endpoint already fixed host and port; requests use its URL.
                await asyncio.to_thread(ensure_server, config.llm.model,
                    extra_dir=config.llm.llamacpp_dir, host=config.llm.llamacpp_host,
                    port=config.llm.llamacpp_port, ctx=config.llm.llamacpp_ctx,
                    threads=config.llm.llamacpp_threads,
                    allow_partial_offload=config.llm.llamacpp_allow_partial_offload)
            self.assets, self.library = cache, target
            self.profiles_applied = True
            self.phase = "ready" if target["enabled"] else "disabled"
            self.error = ""
            self._pending_library = None
        finally:
            self._apply_waiting = False
        return self.snapshot()

    async def apply_greeting(self, profile_id, *, expected_revision):
        if self._apply_waiting:
            raise ProfileError("設定正在套用，請稍候", 409)
        if profile_id != self.current_id:
            raise ProfileError("主數位人已變更，請在招呼頁重新載入設定", 409)
        saved = self.store.load()
        if type(expected_revision) is not int or expected_revision != saved["revision"]:
            raise ProfileError("設定已更新，請重新載入招呼設定", 409)
        profile = next((p for p in saved["profiles"] if p["id"] == profile_id), None)
        if profile is None:
            raise ProfileError("找不到主數位人設定，請重新載入", 409)
        try:
            greeting = validate_content(profile.get("greeting"), required=self.state.config.stage.idle_greeting_enabled)
        except ValueError as exc:
            raise ProfileError(str(exc)) from exc
        self.profiles[profile_id]["greeting"] = deepcopy(greeting)
        active_values, saved_values = deepcopy(self.library), deepcopy(saved)
        active_values.pop("revision", None)
        saved_values.pop("revision", None)
        if active_values == saved_values:
            self.library["revision"] = saved["revision"]
        return self.snapshot()

    def config_for_session(self):
        config = (profile_config(self.state.config, self.profiles[self.current_id])
                  if self.profiles_applied or self.enabled else deepcopy(self.state.config))
        config.conversation_snapshot = True
        config.role_library_snapshot = deepcopy(self.library)
        return config

    def data_for_session(self):
        return self.assets[self.profiles[self.current_id]["avatar_id"]] if self.profiles_applied or self.enabled else self.state.avatar

    def register(self, voice):
        roles = ConversationRoles(self, voice)
        self.sessions[voice.sessionid] = roles
        voice._role_coordinator = roles
        if self.enabled:
            voice.avatar._role_presentation = RolePresentation()
        if self.profiles_applied or self.enabled:
            select_session_profile(voice.sessionid, roles.current_id)
        roles.notify()

    def unregister(self, sessionid):
        roles = self.sessions.pop(sessionid, None)
        if roles:
            roles.cancel(sessionid)

    async def apply_pending(self):
        if not self.state.avatar_streams and self._pending_library is not None:
            try:
                await self.apply(self._pending_library)
            except Exception:
                self.error = "設定待套用：請檢查引擎與模型後重試"
                logger.exception("Deferred role settings could not be applied")

    async def restart_conversation(self, voice, previous):
        # Called only by automatic full reset, never by display clearing,
        # manual history clearing or a role handoff.
        if previous.enabled and previous.current_id != previous.library["pair"]["main"]:
            await previous._switch(previous.library["pair"]["main"], voice)
        config = self.config_for_session()
        if hasattr(voice.avatar, "bind_profile") and (self.profiles_applied or self.enabled):
            await _bind_avatar(voice.avatar, config, self.data_for_session())
        else:
            voice.avatar.config = config
        if voice._closed or self.sessions.get(voice.sessionid) is not previous:
            return
        await previous.close()
        from src.llm.service import remove_session
        remove_session(voice.sessionid)
        voice.config = voice.avatar.config
        roles = ConversationRoles(self, voice)
        voice._turn_context = None
        voice.bind_conversation()
        if getattr(voice.avatar, "tts", None) is not None:
            voice.avatar.tts.config = voice.config
        voice.avatar._role_presentation = RolePresentation() if roles.enabled else None
        self.sessions[voice.sessionid] = roles
        voice._role_coordinator = roles
        select_session_profile(voice.sessionid, roles.current_id)
        if voice._media_player is not None:
            voice._media_player.discard_stale_media()
        roles.notify()

    async def return_to_main(self, requester):
        roles = self.sessions.get(requester.sessionid)
        if roles is None:
            raise ProfileError("對話已結束，請重新連線", 404)
        return await roles.return_to_main(requester)

    async def close(self):
        for roles in list(self.sessions.values()):
            await roles.close()
        self.sessions.clear()
        self.routing_clients.close()


async def initialize_roles(state):
    if state.config is None:
        return None
    path = Path(state.config_path or "config/config.yaml").parent / "avatar_profiles.yaml"
    store = ProfileStore(path)
    library = await asyncio.to_thread(store.initialize, state.config)
    coordinator = RoleCoordinator(state, store, library)
    state.roles = coordinator
    try:
        await coordinator.apply(startup=True)
    except Exception:
        logger.exception("數位人設定檔載入失敗，保持原數位人服務")
        coordinator.phase = "disabled"
        coordinator.error = "數位人設定檔尚未就緒，請檢查設定並重新套用"
    return coordinator
