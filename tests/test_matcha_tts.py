# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The CPU-only Matcha-TTS engine and how role profiles choose its voice model.

No real weights are loaded: sherpa-onnx is replaced by a fake module and each
voice model is a fixture directory whose ``model.onnx`` is a tiny real ONNX
graph carrying the ``model_type`` metadata the engine checks.
"""

from __future__ import annotations

import importlib.machinery
import json
import shutil
import logging
import sys
import types
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from src.config.schema import Config
from src.tts.factory import create_tts_engine

LABEL = {
    "name": "曉臻（測試）",
    "usage": "Development only",
    "languages": ["zh-TW", "en-US"],
    "source": "fixture for tests",
}
VOICE_ID = "zh-tw-fixture"


def _varint(number: int) -> bytes:
    out = bytearray()
    while True:
        byte, number = number & 0x7F, number >> 7
        out.append(byte | 0x80 if number else byte)
        if not number:
            return bytes(out)


def _field(number: int, payload: int | str | bytes) -> bytes:
    if isinstance(payload, int):
        return _varint(number << 3) + _varint(payload)
    data = payload.encode() if isinstance(payload, str) else payload
    return _varint(number << 3 | 2) + _varint(len(data)) + data


def tiny_onnx(metadata: dict[str, str]) -> bytes:
    """A one-node (Identity) ONNX model with ``metadata``, encoded by hand.

    Field numbers follow onnx.proto (ModelProto, GraphProto, NodeProto,
    ValueInfoProto, TypeProto); the project has no ``onnx`` dependency.
    """
    float_1d = _field(1, 1) + _field(2, _field(1, _field(1, 1)))

    def value(name: str) -> bytes:
        return _field(1, name) + _field(2, _field(1, float_1d))

    node = _field(1, "x") + _field(2, "y") + _field(4, "Identity")
    graph = _field(1, node) + _field(2, "g") + _field(11, value("x")) + _field(12, value("y"))
    model = _field(1, 8) + _field(8, _field(2, 13)) + _field(7, graph)
    for key, text in metadata.items():
        model += _field(14, _field(1, key) + _field(2, text))
    return model


def make_voice_model(root: Path, model_id: str = VOICE_ID, *, model_type: str = "matcha-tts") -> Path:
    model_dir = root / model_id
    model_dir.mkdir(parents=True)
    (model_dir / "model.onnx").write_bytes(tiny_onnx({"model_type": model_type}))
    (model_dir / "vocos-16khz-univ.onnx").write_bytes(b"vocoder fixture")
    (model_dir / "tokens.txt").write_text("  1\nni3 2\nhao3 3\n", encoding="utf-8")
    (model_dir / "lexicon.txt").write_text(
        "什么 shen2 me5\n软件 ruan3 jian4\nnova n ˈ O v ə\navatar ˈ æ v ə t ˌ ɑ ɹ\n"
        "ai ˈ A ˌ I\na A\np p ˈ i\ni ˈ I\n",
        encoding="utf-8",
    )
    (model_dir / "number-zh.fst").write_bytes(b"fst fixture")
    (model_dir / "voice.json").write_text(json.dumps(LABEL), encoding="utf-8")
    return model_dir


class FakeSherpa(types.ModuleType):
    """The slice of the sherpa-onnx API the engine uses; records what it is given."""

    def __init__(self, samples: np.ndarray, sample_rate: int = 16000):
        super().__init__("sherpa_onnx")
        self.__spec__ = importlib.machinery.ModuleSpec("sherpa_onnx", None)
        self.instances: list = []
        fake = self

        class Config:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

            def validate(self):
                return True

        class OfflineTts:
            def __init__(self, config):
                self.config = config
                self.texts: list[str] = []
                fake.instances.append(self)

            def generate(self, text, sid=0, speed=1.0, callback=None):
                self.texts.append(text)
                return types.SimpleNamespace(samples=samples, sample_rate=sample_rate)

        self.OfflineTtsMatchaModelConfig = Config
        self.OfflineTtsModelConfig = Config
        self.OfflineTtsConfig = Config
        self.OfflineTts = OfflineTts


class Parent:
    def __init__(self) -> None:
        self.frames: list[tuple[np.ndarray, dict]] = []
        self.failures: list[tuple[dict, str]] = []

    def put_audio_frame(self, samples, eventpoint=None) -> None:
        self.frames.append((np.asarray(samples, dtype=np.float32).copy(), dict(eventpoint or {})))

    def notify_fragment_synthesis_failed(self, eventpoint: dict, reason: str) -> None:
        self.failures.append((dict(eventpoint), reason))


def tone(seconds: float = 0.2, amplitude: float = 0.3) -> np.ndarray:
    t = np.linspace(0.0, seconds, int(16000 * seconds), endpoint=False, dtype=np.float32)
    return (amplitude * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)


@pytest.fixture
def voice_models(tmp_path, monkeypatch):
    root = tmp_path / "models" / "tts"
    root.mkdir(parents=True)
    monkeypatch.setattr("src.tts.voice_models.VOICE_MODELS_ROOT", root)
    return root


@pytest.fixture
def sherpa(monkeypatch):
    def install(samples: np.ndarray | None = None, sample_rate: int = 16000) -> FakeSherpa:
        module = FakeSherpa(tone() if samples is None else samples, sample_rate)
        monkeypatch.setitem(sys.modules, "sherpa_onnx", module)
        return module

    return install


def matcha_config(voice_model: str = VOICE_ID) -> Config:
    config = Config()
    config.tts.type = "matcha"
    config.tts.ref_file = voice_model
    return config


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
    from src.tts.engines.matcha import normalize_matcha_text

    assert (normalize_matcha_text("我會用自然、口語化的方式，提供準確、有用的資訊。")
            == "我會用自然口語化的方式，提供準確有用的資訊。")


def test_thread_count_is_a_server_setting_read_from_the_configuration_file():
    from src.config.loader import dict_to_config

    assert dict_to_config({}).matcha.num_threads == 4
    assert dict_to_config({"matcha": {"num_threads": 8}}).matcha.num_threads == 8
    for bad in (0, -1, True, "4", 65):
        with pytest.raises(ValueError, match="matcha.num_threads"):
            dict_to_config({"matcha": {"num_threads": bad}})


@pytest.fixture
def store(tmp_path, monkeypatch):
    from src.profiles.store import ProfileStore

    monkeypatch.setattr("src.profiles.store.avatar_settings", lambda _: {"enabled": False, "dataset_ids": []})
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
    from src.profiles.store import ProfileError

    make_voice_model(voice_models)
    for voice_model, message in (("", "選擇聲線模型"), ("zh-tw-missing", "zh-tw-missing」不在 models/tts 清單中")):
        with pytest.raises(ProfileError, match=message):
            _save_voice(store, type="matcha", ref_file=voice_model)

    saved = _save_voice(store, type="matcha", ref_file=VOICE_ID, tts_server="", model="")

    assert saved["profiles"][0]["tts"]["type"] == "matcha"
    assert saved["profiles"][0]["tts"]["ref_file"] == VOICE_ID


def test_saved_voice_model_that_is_gone_is_cleared_and_never_replaced(voice_models, store, caplog):
    model_dir = make_voice_model(voice_models)
    _save_voice(store, type="matcha", ref_file=VOICE_ID)
    shutil.rmtree(model_dir)

    with caplog.at_level(logging.WARNING):
        library = store.initialize(store.config)

    tts = library["profiles"][0]["tts"]
    assert (tts["type"], tts["ref_file"]) == ("matcha", "")
    assert f"聲線模型「{VOICE_ID}」" in caplog.text


def test_console_lists_matcha_and_only_labelled_voice_models(voice_models):
    from src.server.runtime_settings import speech_snapshot

    make_voice_model(voice_models)
    (voice_models / "matcha-base").mkdir()

    tts = speech_snapshot(Config())["tts"]

    [matcha] = [engine for engine in tts["engines"] if engine["id"] == "matcha"]
    assert "Non-commercial" in matcha["label"]
    assert matcha["available"] is True
    assert tts["voice_models"] == [{"id": VOICE_ID, **LABEL}]


def test_profile_preview_speaks_with_the_chosen_voice_model(voice_models, sherpa):
    from src.server.runtime_settings import SettingsError, preview_profile_voice

    make_voice_model(voice_models)
    fake = sherpa()
    for voice_model, message in (("", "選擇聲線模型"), ("zh-tw-missing", "zh-tw-missing」不在 models/tts 清單中")):
        with pytest.raises(SettingsError, match=message):
            preview_profile_voice(Config(), {"type": "matcha", "ref_file": voice_model}, session_count=0)

    audio = preview_profile_voice(Config(), {"type": "matcha", "ref_file": VOICE_ID}, session_count=1)

    assert audio.startswith("data:audio/wav;base64,")
    assert fake.instances[0].texts


def test_matcha_speaks_both_conversation_languages():
    from src.server.conversations import check_language_support

    config = matcha_config()
    for locale in ("zh-TW", "en-US"):
        check_language_support(config, locale)
