# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The CPU-only Matcha-TTS engine and how role profiles choose its voice model.

No real weights are loaded: sherpa-onnx is replaced by a fake module and each
voice model is a fixture directory whose ``model.onnx`` is a tiny real ONNX
graph carrying the ``model_type`` metadata the engine checks.
"""

from __future__ import annotations

import shutil
import logging
import sys
import threading
import time
from copy import deepcopy

import numpy as np
import pytest

from nova_core.config.schema import Config
from nova_tts.factory import create_tts_engine
from tests.matcha_fakes import FakeSherpa, LABEL, Parent, VOICE_ID, make_voice_model, matcha_config, tone  # noqa: F401


@pytest.fixture
def voice_models(tmp_path, monkeypatch):
    root = tmp_path / "models" / "tts"
    root.mkdir(parents=True)
    monkeypatch.setattr("nova_tts.voice_models.VOICE_MODELS_ROOT", root)
    return root


@pytest.fixture
def sherpa(monkeypatch):
    def install(samples: np.ndarray | None = None, sample_rate: int = 16000) -> FakeSherpa:
        module = FakeSherpa(tone() if samples is None else samples, sample_rate)
        monkeypatch.setitem(sys.modules, "sherpa_onnx", module)
        return module

    return install


TURN = {"turn_id": "turn-1", "generation": 2, "fragment_sequence": 0}


def test_profile_voice_model_speaks_a_turn_in_20ms_frames(voice_models, sherpa, caplog):
    make_voice_model(voice_models)
    fake = sherpa()
    parent = Parent()

    engine = create_tts_engine("matcha", matcha_config(), parent)
    with caplog.at_level(logging.INFO):
        engine.txt_to_audio(("您好，歡迎光臨。", dict(TURN)))

    assert parent.failures == []
    assert len(parent.frames) > 2
    assert all(frame.shape == (320,) for frame, _ in parent.frames)
    first, last = parent.frames[0][1], parent.frames[-1][1]
    assert first["status"] == "start" and first["fragment_start"] is True
    assert last["status"] == "end" and last["fragment_end"] is True
    assert [ep["media_sequence"] for _, ep in parent.frames] == list(range(len(parent.frames)))
    assert "matcha first audio:" in caplog.text
    [tts] = fake.instances
    assert tts.config.model.matcha.acoustic_model.endswith(f"{VOICE_ID}/model.onnx")
    assert tts.config.model.provider == "cpu"


@pytest.mark.parametrize(
    ("voice_model", "named"),
    [("", "選擇聲線模型"), ("zh-tw-missing", "聲線模型「zh-tw-missing」不在 models/tts 清單中")],
)
def test_unchosen_or_missing_voice_model_fails_every_fragment_without_another_voice(
        voice_models, sherpa, voice_model, named):
    make_voice_model(voice_models, "zh-tw-other")
    fake = sherpa()
    parent = Parent()

    engine = create_tts_engine("matcha", matcha_config(voice_model), parent)
    for _ in range(2):
        with pytest.raises(RuntimeError, match=named):
            engine.txt_to_audio(("您好。", dict(TURN)))

    assert parent.frames == []
    assert [reason for _, reason in parent.failures] == ["tts_exhausted_before_audio"] * 2
    assert fake.instances == []


def test_voice_model_that_is_not_matcha_is_refused_before_sherpa_loads_it(voice_models, sherpa):
    make_voice_model(voice_models, model_type="vits")
    fake = sherpa()
    parent = Parent()

    engine = create_tts_engine("matcha", matcha_config(), parent)
    with pytest.raises(RuntimeError, match="不是 Matcha-TTS 模型"):
        engine.txt_to_audio(("您好。", dict(TURN)))

    assert fake.instances == []
    assert parent.frames == []


def test_server_thread_count_applies_and_roles_share_one_loaded_voice_model(voice_models, sherpa):
    make_voice_model(voice_models)
    fake = sherpa()
    config = matcha_config()
    config.matcha.num_threads = 2

    create_tts_engine("matcha", config, Parent())
    create_tts_engine("matcha", config, Parent())

    [tts] = fake.instances
    assert tts.config.model.num_threads == 2
    assert tts.config.model.matcha.length_scale == 1.0
    assert tts.config.model.matcha.noise_scale == 0.667
    assert Config().matcha.num_threads == 4


def test_loud_output_is_scaled_below_full_scale(voice_models, sherpa):
    make_voice_model(voice_models)
    sherpa(np.full(3200, 1.45, dtype=np.float32))
    parent = Parent()

    create_tts_engine("matcha", matcha_config(), parent).txt_to_audio(("測試峰值。", dict(TURN)))

    assert parent.frames
    assert max(float(np.max(np.abs(frame))) for frame, _ in parent.frames) <= 0.8801


def test_empty_synthesis_reports_the_fragment_as_failed(voice_models, sherpa):
    make_voice_model(voice_models)
    sherpa(np.empty(0, dtype=np.float32))
    parent = Parent()

    create_tts_engine("matcha", matcha_config(), parent).txt_to_audio(("測試。", dict(TURN)))

    assert parent.frames == []
    assert [reason for _, reason in parent.failures] == ["tts_empty_audio"]


def test_text_is_simplified_and_english_spelled_as_the_lexicon_knows_it(voice_models, sherpa):
    make_voice_model(voice_models)
    fake = sherpa()

    create_tts_engine("matcha", matcha_config(), Parent()).txt_to_audio(
        ("為什麼 `NovaAvatar` 的 **API** 與 AI 軟體這麼快？", dict(TURN)))

    [text] = fake.instances[0].texts
    assert "什么" in text and "软件" in text
    assert "nova avatar" in text
    assert "a p i" in text
    assert " ai " in text


def test_enumeration_commas_between_chinese_words_do_not_split_clauses():
    from nova_tts.engines.matcha import normalize_matcha_text

    assert (normalize_matcha_text("我會用自然、口語化的方式，提供準確、有用的資訊。")
            == "我會用自然口語化的方式，提供準確有用的資訊。")


def test_thread_count_is_a_server_setting_read_from_the_configuration_file():
    from nova_core.config.loader import dict_to_config

    assert dict_to_config({}).matcha.num_threads == 4
    assert dict_to_config({"matcha": {"num_threads": 8}}).matcha.num_threads == 8
    for bad in (0, -1, True, "4", 65):
        with pytest.raises(ValueError, match="matcha.num_threads"):
            dict_to_config({"matcha": {"num_threads": bad}})


@pytest.fixture
def store(tmp_path, monkeypatch):
    from nova_core.profiles.store import ProfileStore

    monkeypatch.setattr("nova_core.profiles.store.avatar_settings", lambda _: {"enabled": False, "dataset_ids": []})
    config = Config()
    config.model.avatar_id = "musetalk_angela"
    profiles = ProfileStore(tmp_path / "profiles.yaml")
    profiles.initialize(config)
    profiles.config = config
    return profiles


def _save_voice(store, **tts):
    library = store.load()
    profiles = deepcopy(library["profiles"])
    profiles[0]["tts"].update(tts)
    return store.save_profiles(profiles, expected_revision=library["profiles_revision"])


def test_profiles_save_only_a_listed_voice_model_for_matcha(voice_models, store):
    from nova_core.profiles.store import ProfileError

    make_voice_model(voice_models)
    for voice_model, message in (("", "選擇聲線模型"), ("zh-tw-missing", "zh-tw-missing」不在 models/tts 清單中")):
        with pytest.raises(ProfileError, match=message):
            _save_voice(store, type="matcha", ref_file=voice_model)

    saved = _save_voice(store, type="matcha", ref_file=VOICE_ID, tts_server="", model="")

    assert saved["profiles"][0]["tts"]["type"] == "matcha"
    assert saved["profiles"][0]["tts"]["ref_file"] == VOICE_ID


def test_saved_voice_model_that_is_gone_stays_selected_and_is_never_replaced(voice_models, store):
    model_dir = make_voice_model(voice_models)
    _save_voice(store, type="matcha", ref_file=VOICE_ID)
    shutil.rmtree(model_dir)

    loaded = store.load()
    restarted = store.initialize(store.config)

    for library in (loaded, restarted, store.load()):
        tts = library["profiles"][0]["tts"]
        assert (tts["type"], tts["ref_file"]) == ("matcha", VOICE_ID)
    with pytest.raises(Exception, match=f"聲線模型「{VOICE_ID}」不在 models/tts 清單中"):
        _save_voice(store, type="matcha", ref_file=VOICE_ID)


def test_saved_voice_model_id_that_breaks_the_id_format_is_cleared(voice_models, store, caplog):
    import yaml

    raw = yaml.safe_load(store.path.read_text("utf-8"))
    raw["profiles"][0]["tts"].update(type="matcha", ref_file="../escape")
    store.path.write_text(yaml.safe_dump(raw, allow_unicode=True), "utf-8")

    with caplog.at_level(logging.WARNING):
        library = store.initialize(store.config)

    tts = library["profiles"][0]["tts"]
    assert (tts["type"], tts["ref_file"]) == ("matcha", "")
    assert "../escape" in caplog.text


def test_applying_a_missing_voice_model_names_it(voice_models, sherpa):
    from nova_core.server.runtime_settings import SettingsError, apply_tts_settings

    make_voice_model(voice_models)
    sherpa()
    for voice_model, message in (("", "選擇聲線模型"), ("zh-tw-missing", "zh-tw-missing」不在 models/tts 清單中")):
        with pytest.raises(SettingsError, match=message):
            apply_tts_settings(Config(), {"type": "matcha", "ref_file": voice_model}, session_count=0)


def test_console_lists_matcha_and_only_labelled_voice_models(voice_models):
    from nova_core.server.runtime_settings import speech_snapshot

    make_voice_model(voice_models)
    (voice_models / "matcha-base").mkdir()

    tts = speech_snapshot(Config())["tts"]

    [matcha] = [engine for engine in tts["engines"] if engine["id"] == "matcha"]
    assert "Non-commercial" in matcha["label"]
    assert matcha["available"] is True
    assert tts["voice_models"] == [{"id": VOICE_ID, **LABEL}]


def test_profile_preview_speaks_with_the_chosen_voice_model(voice_models, sherpa):
    from nova_core.server.runtime_settings import SettingsError, preview_profile_voice

    make_voice_model(voice_models)
    fake = sherpa()
    for voice_model, message in (("", "選擇聲線模型"), ("zh-tw-missing", "zh-tw-missing」不在 models/tts 清單中")):
        with pytest.raises(SettingsError, match=message):
            preview_profile_voice(Config(), {"type": "matcha", "ref_file": voice_model}, session_count=0)

    audio = preview_profile_voice(Config(), {"type": "matcha", "ref_file": VOICE_ID}, session_count=1)

    assert audio.startswith("data:audio/wav;base64,")
    assert fake.instances[0].texts


def test_matcha_speaks_both_conversation_languages():
    from nova_core.server.conversations import check_language_support

    config = matcha_config()
    for locale in ("zh-TW", "en-US"):
        check_language_support(config, locale)


# --- Fragment prefetch: while fragment N plays, fragment N+1 is synthesised and held. ---


def turn(sequence: int, turn_id: str = "turn-1", generation: int = 1) -> dict:
    return {"turn_id": turn_id, "generation": generation, "fragment_sequence": sequence}


class ClockParent(Parent):
    """Plays emitted 20 ms frames back to back on a simulated audio clock."""

    def __init__(self) -> None:
        super().__init__()
        self.clock = 0.0  # when the queued audio runs out, in monotonic seconds
        self.starts: dict[tuple[str, int], tuple[float, float]] = {}  # fragment -> (queued-at, plays-at)
        self.ends: dict[tuple[str, int], float] = {}
        self.block_first_frame_of: threading.Event | None = None
        self.lock = threading.Lock()

    def put_audio_frame(self, samples, eventpoint=None) -> None:
        ep = dict(eventpoint or {})
        key = (ep["turn_id"], ep["fragment_sequence"])
        if ep.get("media_sequence") == 0 and self.block_first_frame_of is not None and key[1] == 0:
            self.block_first_frame_of.wait(timeout=5)
        with self.lock:
            now = time.monotonic()
            plays_at = max(now, self.clock)
            self.starts.setdefault(key, (now, plays_at))
            self.clock = plays_at + 0.02
            self.ends[key] = self.clock
            super().put_audio_frame(samples, ep)

    def fragment_playback_ended(self, eventpoint: dict) -> bool:
        key = (eventpoint["turn_id"], eventpoint["fragment_sequence"])
        with self.lock:
            return key in self.ends and time.monotonic() >= self.ends[key]

    def emitted(self) -> list[tuple[str, int]]:
        seen: list[tuple[str, int]] = []
        for _, ep in list(self.frames):
            key = (ep["turn_id"], ep["fragment_sequence"])
            if key not in seen:
                seen.append(key)
        return seen


class SlowSherpa(FakeSherpa):
    """Synthesis takes ``delay`` seconds; ``gates`` can hold a text until released."""

    def __init__(self, samples, delay: float = 0.0):
        super().__init__(samples)
        outer = self
        self.delay = delay
        self.gates: dict[str, threading.Event] = {}
        self.started: dict[str, threading.Event] = {}
        self.running = 0
        self.max_running = 0
        self.guard = threading.Lock()
        base = self.OfflineTts

        class OfflineTts(base):
            def generate(self, text, sid=0, speed=1.0, callback=None):
                with outer.guard:
                    outer.running += 1
                    outer.max_running = max(outer.max_running, outer.running)
                    outer.started.setdefault(text, threading.Event()).set()
                try:
                    gate = outer.gates.get(text)
                    if gate is not None:
                        gate.wait(timeout=5)
                    time.sleep(outer.delay)
                    return super().generate(text, sid, speed, callback)
                finally:
                    with outer.guard:
                        outer.running -= 1

        self.OfflineTts = OfflineTts


@pytest.fixture
def slow_sherpa(monkeypatch):
    def install(samples: np.ndarray | None = None, delay: float = 0.0) -> SlowSherpa:
        module = SlowSherpa(tone(0.4) if samples is None else samples, delay)
        monkeypatch.setitem(sys.modules, "sherpa_onnx", module)
        return module

    return install


@pytest.fixture
def running():
    """Run ``engine.process_tts`` on a thread; stop and join it at teardown."""
    started: list[tuple[threading.Event, threading.Thread]] = []

    def start(engine):
        quit_event = threading.Event()
        thread = threading.Thread(target=engine.process_tts, args=(quit_event,), daemon=True)
        thread.start()
        started.append((quit_event, thread))
        return thread

    yield start
    for quit_event, thread in started:
        quit_event.set()
        thread.join(timeout=3)
        assert not thread.is_alive()


def wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def spoken(fake: SlowSherpa, text: str) -> bool:
    event = fake.started.get(text)
    return event is not None and event.is_set()


def test_next_fragment_is_synthesised_while_the_current_one_plays_so_no_audible_gap(
        voice_models, slow_sherpa, running):
    make_voice_model(voice_models)
    slow_sherpa(delay=0.15)
    parent = ClockParent()
    engine = create_tts_engine("matcha", matcha_config(), parent)
    for sequence in range(3):
        engine.put_msg_txt(f"第{sequence}段。", turn(sequence))

    running(engine)

    assert wait_until(lambda: len(parent.ends) == 3 and parent.fragment_playback_ended(turn(2)))
    for before, after in ((0, 1), (1, 2)):
        gap = parent.starts[("turn-1", after)][1] - parent.ends[("turn-1", before)]
        assert gap < 0.05, f"audible gap {gap * 1000:.0f} ms between fragments {before} and {after}"
    assert parent.emitted() == [("turn-1", 0), ("turn-1", 1), ("turn-1", 2)]
    assert parent.failures == []


def test_only_one_fragment_is_synthesised_ahead_of_the_one_being_emitted(
        voice_models, slow_sherpa, running):
    make_voice_model(voice_models)
    fake = slow_sherpa()
    parent = ClockParent()
    parent.block_first_frame_of = threading.Event()
    engine = create_tts_engine("matcha", matcha_config(), parent)
    for sequence in range(4):
        engine.put_msg_txt(f"第{sequence}段。", turn(sequence))

    running(engine)

    try:
        assert wait_until(lambda: spoken(fake, "第1段。"))
        time.sleep(0.2)
        assert not spoken(fake, "第2段。")
        assert engine.has_pending_work()
    finally:
        parent.block_first_frame_of.set()
    assert wait_until(lambda: len(parent.ends) == 4)
    assert parent.emitted() == [("turn-1", sequence) for sequence in range(4)]


def test_flush_drops_the_held_fragment_and_a_new_turn_plays_without_it(
        voice_models, slow_sherpa, running):
    make_voice_model(voice_models)
    fake = slow_sherpa()
    parent = ClockParent()
    parent.block_first_frame_of = threading.Event()
    engine = create_tts_engine("matcha", matcha_config(), parent)
    engine.put_msg_txt("甲一。", turn(0, "old"))
    engine.put_msg_txt("甲二。", turn(1, "old"))
    running(engine)
    # Fragment 0 is emitting (blocked), fragment 1 is synthesised and held.
    assert wait_until(lambda: spoken(fake, "甲二。"))
    time.sleep(0.1)

    engine.flush_talk()
    parent.block_first_frame_of.set()
    engine.put_msg_txt("乙一。", turn(0, "new", 2))

    assert wait_until(lambda: ("new", 0) in parent.ends and parent.fragment_playback_ended(turn(0, "new", 2)))
    assert ("old", 1) not in parent.emitted()
    assert wait_until(lambda: not engine.has_pending_work())


def test_fragment_still_being_synthesised_at_flush_is_never_played(
        voice_models, slow_sherpa, running):
    make_voice_model(voice_models)
    fake = slow_sherpa()
    fake.gates["甲。"] = threading.Event()
    parent = ClockParent()
    engine = create_tts_engine("matcha", matcha_config(), parent)
    engine.put_msg_txt("甲。", turn(0, "old"))
    running(engine)
    assert wait_until(lambda: spoken(fake, "甲。"))

    engine.flush_talk()
    engine.put_msg_txt("乙。", turn(0, "new", 2))
    fake.gates["甲。"].set()

    assert wait_until(lambda: ("new", 0) in parent.ends and parent.fragment_playback_ended(turn(0, "new", 2)))
    assert [key for key in parent.emitted() if key[0] == "old"] == []
    assert wait_until(lambda: not engine.has_pending_work())


def test_a_fragment_held_for_a_superseded_turn_is_not_played_even_without_a_flush(
        voice_models, slow_sherpa, running):
    make_voice_model(voice_models)
    slow_sherpa()
    parent = ClockParent()
    parent.block_first_frame_of = threading.Event()
    stale = {"turn-1"}
    parent.accepts_media = lambda eventpoint, stage: eventpoint["turn_id"] not in stale
    engine = create_tts_engine("matcha", matcha_config(), parent)
    engine.put_msg_txt("第0段。", turn(0, "turn-2"))
    engine.put_msg_txt("第1段。", turn(0, "turn-1"))
    engine.put_msg_txt("第2段。", turn(1, "turn-2"))

    running(engine)
    parent.block_first_frame_of.set()

    assert wait_until(lambda: ("turn-2", 1) in parent.ends)
    assert ("turn-1", 0) not in parent.emitted()


def test_a_failed_held_fragment_is_reported_when_its_turn_comes_up_and_later_ones_still_play(
        voice_models, sherpa, running, monkeypatch):
    make_voice_model(voice_models)
    sherpa()
    parent = ClockParent()
    engine = create_tts_engine("matcha", matcha_config(), parent)
    real = engine._synthesize

    def synthesize(voice, text, *args, **kwargs):
        if "壞" in text:
            raise RuntimeError("synthesis blew up")
        return real(voice, text, *args, **kwargs)

    monkeypatch.setattr(engine, "_synthesize", synthesize)
    engine.put_msg_txt("好一。", turn(0))
    engine.put_msg_txt("壞的。", turn(1))
    engine.put_msg_txt("好二。", turn(2))

    running(engine)

    assert wait_until(lambda: ("turn-1", 2) in parent.ends)
    assert [(ep["fragment_sequence"], reason) for ep, reason in parent.failures] == [(1, "tts_exhausted_before_audio")]
    assert parent.emitted() == [("turn-1", 0), ("turn-1", 2)]


def test_engines_sharing_a_voice_model_still_synthesise_one_text_at_a_time(
        voice_models, slow_sherpa, running):
    make_voice_model(voice_models)
    fake = slow_sherpa(delay=0.05)
    parents = [ClockParent(), ClockParent()]
    engines = [create_tts_engine("matcha", matcha_config(), parent) for parent in parents]
    for index, engine in enumerate(engines):
        for sequence in range(3):
            engine.put_msg_txt(f"引擎{index}第{sequence}段。", turn(sequence, f"turn-{index}"))
        running(engine)

    assert wait_until(lambda: all(len(parent.ends) == 3 for parent in parents))
    assert fake.max_running == 1
