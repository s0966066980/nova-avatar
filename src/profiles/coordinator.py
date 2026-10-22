# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""One field, one input owner and one server-owned role transition at a time."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
import time
from uuid import uuid4

from src.avatars.factory import load_avatar_data
from src.llm.service import discard_profile_history, select_session_profile, session_history
from src.profiles.media import RolePresentation, TransitionMedia, _VideoReader
from src.profiles.routing import route_question
from src.config.schema import GreetingConfig
from src.greetings.content import validate_content
from src.profiles.store import ProfileError, ProfileStore, compatible_pair, profile_config
from src.profiles.weather import CwaWeather, WeatherQuery
from src.utils.logging import logger


class RoleCoordinator:
    def __init__(self, state, store, library, *, loader=load_avatar_data, router=route_question,
                 weather=None, media=None):
        self.state = state
        self.store = store
        self.library = deepcopy(library)
        self.loader = loader
        self.router = router
        self.weather = weather or CwaWeather()
        self.media = media or TransitionMedia()
        self.current_id = library["pair"]["main"]
        self.mode = "visitor" if state.count_sessions("stage") else "console"
        self.phase = "disabled"
        self.error = ""
        self.assets = {}
        self.profiles_applied = False
        self.pending = {}
        self.continuations = {}
        self.confirmed = {}
        self._lock = asyncio.Lock()
        self._apply_waiting = False
        self._transition_event = None
        self._transition_id = ""
        self._transition_owner = None
        self._visitor_resume_pending = False
        self._console_mode_requested = False

    @property
    def enabled(self):
        return bool(self.library["enabled"] and self.phase != "disabled")

    @property
    def input_mode_managed(self):
        return self.enabled or self.state.config.stage.idle_greeting_enabled

    @property
    def profiles(self):
        return {p["id"]: p for p in self.library["profiles"]}

    def snapshot(self):
        return dict(enabled=self.enabled, input_mode_managed=self.input_mode_managed, phase=self.phase, mode=self.mode,
                    active_profile_id=self.current_id, pair=self.library["pair"],
                    active_revision=self.library["revision"], error=self.error,
                    weather_configured=self.weather.configured,
                    profiles_applied=self.profiles_applied,
                    active_avatar_id=self.profiles[self.current_id]["avatar_id"]
                        if self.profiles_applied or self.enabled else "",
                    can_return=self.enabled and self.current_id == self.library["pair"]["specialist"]
                               and self.phase == "ready", applying=self._apply_waiting)

    def notify(self, session=None):
        presentation = getattr(self.state, "presentation", None)
        if presentation is not None:
            presentation.refresh()
        targets = [session] if session is not None else list(self.state.voice_sessions.values())
        for voice in targets:
            voice._emit("role_state", **self.snapshot())
            voice._refresh_gate()

    def input_allowed(self, session):
        if self._apply_waiting:
            return False
        if not self.input_mode_managed:
            return True
        role = "stage" if self.mode == "visitor" else "console"
        return (session._presenter == role and self.phase in {"ready", "announcement", "disabled"}
                and not self._apply_waiting)

    def all_idle(self):
        return all(v._is_conversation_idle() for v in self.state.voice_sessions.values())

    async def apply(self, library=None, *, startup=False):
        if self._apply_waiting:
            raise ProfileError("設定正在套用，請稍候", 409)
        target = deepcopy(library or self.store.load())
        main = next(p for p in target["profiles"] if p["id"] == target["pair"]["main"])
        if self.state.config.stage.idle_greeting_enabled:
            try:
                validate_content(main.get("greeting"), required=True)
            except ValueError as exc:
                raise ProfileError(str(exc)) from exc
        def without_greetings(value):
            value = deepcopy(value)
            value.pop("revision", None)
            for profile in value["profiles"]:
                profile.pop("greeting", None)
            return value
        greeting_changed = any(new.get("greeting") != old.get("greeting")
                               for new, old in zip(target["profiles"], self.library["profiles"]))
        if self.profiles_applied and greeting_changed and without_greetings(target) == without_greetings(self.library):
            self.library = target
            for voice in self.state.voice_sessions.values():
                voice.config.greeting = GreetingConfig(**self.profiles[self.current_id]["greeting"])
                voice.greetings.refresh()
            self.notify()
            return self.snapshot()
        for voice in self.state.voice_sessions.values():
            if hasattr(voice, "greetings"):
                voice.greetings.reset(stop_playing=False)
        self._apply_waiting = True
        self.notify()
        try:
            deadline = time.monotonic() + 30
            while not startup and (not self.all_idle() or self.phase in {"transition", "announcement"}):
                if time.monotonic() > deadline:
                    raise ProfileError("目前輪次尚未結束，設定已保存，請稍後套用", 409)
                await asyncio.sleep(.05)
            async with self._lock:
                previous = self.library
                main = next(p for p in target["profiles"] if p["id"] == target["pair"]["main"])
                if not target["enabled"]:
                    if main["engine"] != self.state.config.model.type:
                        raise ProfileError("請先在數位人與畫質頁載入設定檔使用的推理引擎", 409)
                    if main["tts"]["type"] != self.state.config.tts.type:
                        raise ProfileError("請先在語音設定頁載入設定檔使用的語音引擎", 409)
                    aid = main["avatar_id"]
                    for voice in self.state.voice_sessions.values():
                        if (not hasattr(voice.avatar, "bind_profile")
                                and voice.config.model.avatar_id != aid):
                            raise ProfileError("此推理引擎切換人物素材前請先中斷連線", 409)
                    if aid == self.state.config.model.avatar_id and self.state.avatar is not None:
                        cache = {aid: self.state.avatar}
                    elif aid in self.assets:
                        cache = {aid: self.assets[aid]}
                    else:
                        from src.avatars.catalog import avatar_bootable
                        valid, reason = avatar_bootable(main["engine"], aid)
                        if not valid:
                            raise ProfileError(reason, 409)
                        cache = {aid: await asyncio.to_thread(
                            self.loader, profile_config(self.state.config, main))}
                if target["enabled"]:
                    main, specialist = compatible_pair(target, self.state.config)
                    if self.state.config.model.type != "musetalk":
                        raise ProfileError("請先在未連線時載入 MuseTalk 引擎", 409)
                    for profile in (main, specialist):
                        from src.avatars.catalog import avatar_bootable, avatar_uses_green_screen
                        valid, reason = avatar_bootable(profile["engine"], profile["avatar_id"])
                        if not valid:
                            raise ProfileError(reason, 409)
                        if not avatar_uses_green_screen(profile["avatar_id"]):
                            raise ProfileError("人物層轉場需要綠幕 MuseTalk 素材", 409)
                    cache = {}
                    for profile in (main, specialist):
                        aid = profile["avatar_id"]
                        if aid not in cache:
                            if aid in self.assets:
                                cache[aid] = self.assets[aid]
                            elif aid == self.state.config.model.avatar_id and self.state.avatar is not None:
                                cache[aid] = self.state.avatar
                            else:
                                cache[aid] = await asyncio.to_thread(
                                    self.loader, profile_config(self.state.config, profile))
                    # Validate all referenced media before changing the runtime.
                    for edge in target["transitions"]:
                        if edge["kind"] == "video":
                            self.media.get(edge["asset_id"])
                config = profile_config(self.state.config, main)
                if config.llm.provider == "llamacpp":
                    from src.llm.llamacpp import ensure_server
                    config.llm.base_url = await asyncio.to_thread(
                        ensure_server, config.llm.model,
                        extra_dir=config.llm.llamacpp_dir,
                        host=config.llm.llamacpp_host, port=config.llm.llamacpp_port,
                        ctx=config.llm.llamacpp_ctx, threads=config.llm.llamacpp_threads)
                    for p in target["profiles"]:
                        if p["id"] == main["id"] or (target["enabled"] and p["id"] == specialist["id"]):
                            p["llm"]["base_url"] = config.llm.base_url
                self.assets = cache
                self.library = target
                self.profiles_applied = True
                self.current_id = target["pair"]["main"]
                for old in previous["profiles"]:
                    new = self.profiles.get(old["id"])
                    if new is None or any(old.get(k) != new.get(k) for k in ("assistant_profile", "llm", "rag")):
                        for sid in self.state.voice_sessions:
                            discard_profile_history(sid, old["id"])
                            self.state.voice_sessions[sid]._emit("role_history_reset", reset_profile_id=old["id"])
                for voice in list(self.state.voice_sessions.values()):
                    voice._emit("board_clear")
                    voice._emit("role_clear")
                    if hasattr(voice.avatar, "bind_profile"):
                        await self._bind_async(voice, self.current_id)
                    else:
                        voice.config = profile_config(self.state.config, main)
                        voice.avatar.config = voice.config
                        if getattr(voice.avatar, "tts", None) is not None:
                            voice.avatar.tts.config = voice.config
                        voice._turn_context = None
                        select_session_profile(voice.sessionid, self.current_id)
                    if not target["enabled"]:
                        presentation = getattr(voice.avatar, "_role_presentation", None)
                        if presentation:
                            presentation.close()
                        voice.avatar._role_presentation = None
                self.phase = "ready" if target["enabled"] else "disabled"
                self.error = ""
        finally:
            self._apply_waiting = False
            self.notify()
        return self.snapshot()

    async def apply_greeting(self, profile_id, *, expected_revision):
        """Publish only the active main's greeting, preserving other saved drafts."""
        if self._apply_waiting or self._lock.locked():
            raise ProfileError("設定正在套用，請稍候再套用招呼", 409)
        if profile_id != self.library["pair"]["main"]:
            raise ProfileError("主數位人已變更，請在招呼頁重新載入設定", 409)
        saved = self.store.load()
        if type(expected_revision) is not int or expected_revision != saved["revision"]:
            raise ProfileError("設定已更新，請重新載入招呼設定", 409)
        profile = next((p for p in saved["profiles"] if p["id"] == profile_id), None)
        if profile is None:
            raise ProfileError("找不到主數位人設定，請重新載入", 409)
        try:
            greeting = validate_content(profile.get("greeting"),
                                        required=self.state.config.stage.idle_greeting_enabled)
        except ValueError as exc:
            raise ProfileError(str(exc)) from exc
        self.profiles[profile_id]["greeting"] = deepcopy(greeting)
        # A greeting save must not claim unrelated role drafts were applied.
        active_values, saved_values = deepcopy(self.library), deepcopy(saved)
        active_values.pop("revision", None)
        saved_values.pop("revision", None)
        if active_values == saved_values:
            self.library["revision"] = saved["revision"]
        for voice in self.state.voice_sessions.values():
            if getattr(voice.config, "profile_id", self.current_id) == profile_id:
                voice.config.greeting = GreetingConfig(**deepcopy(greeting))
            voice.greetings.refresh()
        self.notify()
        return self.snapshot()

    def config_for_session(self):
        return profile_config(self.state.config, self.profiles[self.current_id]) if self.profiles_applied or self.enabled else self.state.config

    def data_for_session(self):
        return self.assets[self.profiles[self.current_id]["avatar_id"]] if self.profiles_applied or self.enabled else self.state.avatar

    def register(self, voice):
        voice._role_coordinator = self
        if self.enabled:
            voice.avatar._role_presentation = RolePresentation()
            if getattr(voice.config, "profile_id", "") != self.current_id:
                self._bind(voice, self.current_id)
            select_session_profile(voice.sessionid, self.current_id)
            if voice._presenter == "stage" and not self._console_mode_requested:
                self._visitor_resume_pending = True
                self.reconcile_input_owner()
        elif self.profiles_applied:
            select_session_profile(voice.sessionid, self.current_id)
        if voice._presenter == "stage" and not self.enabled and not self._console_mode_requested:
            self._visitor_resume_pending = True
            self.reconcile_input_owner()
        self.notify()

    def unregister(self, sessionid):
        self.cancel(sessionid)
        self.confirmed.pop(sessionid, None)
        self.continuations.pop(sessionid, None)
        if not self.state.count_sessions("stage"):
            self.mode = "console"
            self._visitor_resume_pending = False
        self.notify()

    async def set_mode(self, mode):
        if mode not in {"visitor", "console"}:
            raise ProfileError("請選擇訪客或控制台測試模式")
        for voice in self.state.voice_sessions.values():
            if hasattr(voice, "greetings"):
                voice.greetings.reset(stop_playing=True)
        if not self.all_idle() or self.phase in {"announcement", "transition"}:
            raise ProfileError("請先等目前輪次結束，或停止目前回答後再切換輸入來源", 409)
        self.mode = mode
        self._console_mode_requested = mode == "console"
        self._visitor_resume_pending = False
        self.notify()
        return self.snapshot()

    def reconcile_input_owner(self):
        if (self._visitor_resume_pending and self.phase in {"ready", "disabled"} and not self._apply_waiting
                and not self.pending and not self.continuations and self.all_idle()):
            self._visitor_resume_pending = False
            self.mode = "visitor"
            self.notify()

    def _bind(self, voice, profile_id):
        profile = self.profiles[profile_id]
        config = profile_config(self.state.config, profile)
        voice.avatar.bind_profile(config, self.assets[profile["avatar_id"]])
        self._finish_binding(voice, profile_id)

    async def _bind_async(self, voice, profile_id):
        profile = self.profiles[profile_id]
        config = profile_config(self.state.config, profile)
        # Building per-avatar continuity controllers touches many frames. Keep
        # RTP pacing on the event loop while the asset lock fences the renderer.
        await asyncio.to_thread(voice.avatar.bind_profile, config, self.assets[profile["avatar_id"]])
        self._finish_binding(voice, profile_id)

    def _finish_binding(self, voice, profile_id):
        voice.config = voice.avatar.config
        voice._turn_context = None
        select_session_profile(voice.sessionid, profile_id)
        if getattr(voice.avatar, "_role_presentation", None) is None:
            voice.avatar._role_presentation = RolePresentation()
        if voice._media_player is not None:
            voice._media_player.discard_stale_media()

    async def before_generate(self, voice, text, turn_id, generation):
        if not self.enabled:
            return None
        sid = voice.sessionid
        continuation = self.continuations.pop(sid, None)
        if continuation:
            result = await continuation["weather_task"] if continuation.get("weather_task") else None
            return {"weather": result, "context": continuation.get("context", "")}
        if not self.input_allowed(voice):
            return {"fixed": "目前由另一個輸入來源接收問題，請先切換輸入模式。"}
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
        if route["route"] != "specialist":
            if self.current_id == specialist_id:
                return {"fixed": f"這個問題可以按返回，交由{self.profiles[self.library['pair']['main']]['name']}接著回答。"}
            if route.get("county") and route.get("town"):
                self.confirmed[sid] = {"county": route["county"], "town": route["town"]}
            return {"context": "本輪未取得即時氣象資料，不可提供實際即時天氣數值。"}
        target = self.profiles[specialist_id]
        weather_task = None
        if target["tools"]["weather"]:
            if not route.get("county"):
                return {"fixed": "請問您想查詢哪個縣市的天氣？"}
            town = route.get("town", "")
            self.confirmed[sid] = {"county": route["county"], "town": town}
            weather_query = WeatherQuery(route["county"], town, route["kind"],
                                         route["start_date"], route["end_date"], route.get("accepted_at", ""))
            weather_task = asyncio.create_task(self.weather.query(weather_query))
        if self.current_id == specialist_id:
            result = await weather_task if weather_task else None
            return {"weather": result, "context": route.get("context", "")}
        pending = dict(id=uuid4().hex, question=text, source_turn=turn_id,
                       generation=generation, weather_task=weather_task,
                       context=route.get("context", ""), readers={})
        self.pending[sid] = pending
        try:
            edge = self.edge(self.current_id, specialist_id)
            if edge["kind"] == "video":
                info, path = self.media.get(edge["asset_id"])
                for other in list(self.state.voice_sessions.values()):
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
        return {"fixed": self.library["handoff"]["announcement"], "handoff_id": pending["id"]}

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
            await self._switch(self.library["pair"]["specialist"], voice,
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
            self.cancel(voice.sessionid)
            raise
        except Exception:
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
            for voice in self.state.voice_sessions.values():
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
                voices = list(self.state.voice_sessions.values())
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
                for voice in list(self.state.voice_sessions.values()):
                    await self._bind_async(voice, source)
                raise
            finally:
                for voice in list(self.state.voice_sessions.values()):
                    presentation = getattr(voice.avatar, "_role_presentation", None)
                    if presentation:
                        presentation.close()
                self.phase = "ready"
                self._transition_event = None
                self.notify()

    async def return_to_main(self, requester):
        if not self.enabled or self.current_id == self.library["pair"]["main"]:
            return self.snapshot()
        owner = next((v for v in self.state.voice_sessions.values() if self.input_allowed(v)), requester)
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
        if self.enabled and voice._presenter == "stage" and self.current_id != self.library["pair"]["main"]:
            voice._greeting_returning = True
            async def return_after_clear():
                try:
                    await self.return_to_main(voice)
                except ProfileError:
                    pass  # return_to_main already publishes the failure
                finally:
                    voice._greeting_returning = False
                    voice.greetings.refresh()
            asyncio.create_task(return_after_clear())

    async def close(self):
        for sid in list(self.pending):
            self.cancel(sid)
        for voice in list(self.state.voice_sessions.values()):
            presentation = getattr(voice.avatar, "_role_presentation", None)
            if presentation:
                presentation.close()


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
