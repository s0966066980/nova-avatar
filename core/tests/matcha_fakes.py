# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Matcha voice-model fakes: a tiny ONNX bundle and a fake sherpa-onnx."""

from __future__ import annotations

import importlib.machinery
import json
import types
from pathlib import Path

import numpy as np

from src.config.schema import Config

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


def matcha_config(voice_model: str = VOICE_ID) -> Config:
    config = Config()
    config.tts.type = "matcha"
    config.tts.ref_file = voice_model
    return config
