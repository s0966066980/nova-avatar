# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Role-coordinator and N-way routing fixtures shared by the handoff tests."""

from __future__ import annotations

import asyncio
import json
import tempfile
from copy import deepcopy
from datetime import datetime
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.config.schema import Config
from src.llm import service
from src.profiles.composition import new_member
from src.profiles.coordinator import RoleCoordinator
from src.profiles.media import RolePresentation
from src.profiles.store import ProfileStore, profile_config
from src.server.voice_session import VoiceTurnSession
from tests.tts_fakes import in_process_tts


class Avatar:
    def __init__(self, config, sid):
        self.config, self.sessionid = config, sid
        self.messages = []
        self._asset_epoch = 0
        self._role_presentation = RolePresentation()

    def configure_media_fence(self, **callbacks):
        self.callbacks = callbacks

    def put_msg_txt(self, text, data):
        self.messages.append((text, data))
        self.callbacks['on_fragment_queued'](text, data)

    def flush_talk(self):
        pass

    def bind_profile(self, config, _data):
        self.config = config
        self._asset_epoch += 1


def route_to(target, **fields):
    """A router decision in ticket 02's shape: a member id, or None to clarify."""
    today = datetime.now().date().isoformat()
    route = dict(target=target, clarification='', context='', county='', town='', kind='',
                 start_date='', end_date='', accepted_at=datetime.now().isoformat(), decided_by='model')
    route.update(fields)
    if route['kind'] and not route['start_date']:
        route.update(start_date=today, end_date=today)
    return route


@pytest.fixture
def field(tmp_path, monkeypatch):
    monkeypatch.setattr(service, '_session_llm_instances', {})
    monkeypatch.setattr(service, '_active_profiles', {})
    monkeypatch.setattr('src.profiles.store.avatar_settings', lambda _: {'enabled': False, 'dataset_ids': []})
    config = Config()
    config.model.type = 'musetalk'
    config.model.avatar_id = 'musetalk_angela'
    config.reply_streaming.enabled = False
    store = ProfileStore(tmp_path / 'profiles.yaml')
    library = store.initialize(config)
    library['composition']['enabled'] = True
    state = SimpleNamespace(config=config, voice_sessions={}, avatar_streams={},
        avatar=object(), tts=in_process_tts(),
        count_sessions=lambda kind: sum(v._presenter == kind for v in state.voice_sessions.values()))
    weather = SimpleNamespace(configured=True, query=Mock())
    route = route_to('weather', county='臺北市', town='中正區', kind='forecast', context='已確認臺北市中正區')
    roles = RoleCoordinator(state, store, library, router=lambda *_: dict(route), weather=weather)
    roles.phase = 'ready'
    roles.assets = {'musetalk_angela': object(), 'musetalk_1': object()}
    return roles


def connect(roles, sid=7, presenter='console'):
    config = profile_config(roles.state.config, roles.profiles[roles.current_id])
    avatar = Avatar(config, sid)
    voice = VoiceTurnSession(sid, config, avatar, presenter=presenter)
    voice._media_player = SimpleNamespace(discard_stale_media=lambda: None)
    roles.state.voice_sessions[sid] = voice
    roles.state.avatar_streams[sid] = avatar
    roles.register(voice)
    events = []
    voice.attach_event_sink(lambda raw: events.append(json.loads(raw)))
    return voice, events


async def wait_until(predicate):
    async def poll():
        while not predicate():
            await asyncio.sleep(.001)
    await asyncio.wait_for(poll(), timeout=3)


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return run


SERVICE = "回答會員、訂單與退換貨問題。"


TRAFFIC = "回答交通路線、停車與接駁車問題。"


def _member(library, profile_id, name, description, rules="", *, enabled=True, weather=False):
    """Add a profile cloned from ``main`` (so it is compatible) and its member entry."""
    profile = deepcopy(next(p for p in library["profiles"] if p["id"] == "main"))
    profile.update(id=profile_id, name=name)
    library["profiles"].append(profile)
    member = new_member(profile_id)
    member.update(enabled=enabled, description=description, rules=rules,
                  announcement=f"接下來請{name}為您說明。")
    member["tools"]["weather"]["enabled"] = weather
    library["composition"]["members"].append(member)
    return member


def composition(*, weather=True, config=None):
    """main + 客服 + 交通 (+ the default weather member when ``weather``), handoff on."""
    config = config or _config()
    library = ProfileStore(Path(tempfile.mkdtemp()) / "profiles.yaml").initialize(config)
    library["composition"]["enabled"] = True
    library["composition"]["main"]["description"] = "公司簡介與一般問題。"
    if not weather:
        library["composition"]["members"] = []
    _member(library, "service", "客服小幫手", SERVICE, "會員或訂單問題交給客服。")
    _member(library, "traffic", "交通嚮導", TRAFFIC)
    _member(library, "archive", "停用角色", "不應出現的專長。", enabled=False)
    return library


def _config():
    config = Config()
    config.llm.provider = "llamacpp"
    config.llm.model = "gemma-4-E2B_q4_0-it"
    config.llm.base_url = "http://127.0.0.1:18080/v1"
    return config


def _prompt(create):
    return create.call_args.kwargs["messages"][0]["content"]


def _schema(create):
    return create.call_args.kwargs["response_format"]["json_schema"]["schema"]
