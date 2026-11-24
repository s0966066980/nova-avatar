# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The three preset preview sentences of a finished voice model (ticket 14).

No real weights are loaded: sherpa-onnx is the fake module of the Matcha engine
tests and each voice model is a fixture directory. The point is what the preview
shares with the live engine (the loader and the per-model lock) and what it
refuses (any text of the caller's own, an unlisted voice model).
"""

from __future__ import annotations

import io
import re
import sys
import threading
import types
import wave
from pathlib import Path

import numpy as np
import pytest

from src.config.schema import Config
from src.tts.engines import matcha
from src.tts.factory import create_tts_engine
from src.tts.voice_preview import (
    MAX_PREVIEW_SECONDS,
    PREVIEW_SENTENCES,
    PreviewError,
    synthesize_preview,
)
from tests.test_matcha_tts import VOICE_ID, FakeSherpa, Parent, make_voice_model, matcha_config, tone


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


def read_wav(data: bytes) -> tuple[wave._wave_params, np.ndarray]:
    with wave.open(io.BytesIO(data)) as reader:
        frames = reader.readframes(reader.getnframes())
        return reader.getparams(), np.frombuffer(frames, dtype="<i2")


def test_the_three_sentence_codes_are_chinese_chinese_with_digits_and_english():
    assert list(PREVIEW_SENTENCES) == ["zh", "digits", "en"]
    assert any(ch.isdigit() for ch in PREVIEW_SENTENCES["digits"])
    assert PREVIEW_SENTENCES["en"].isascii()
    assert not any(ch.isdigit() for ch in PREVIEW_SENTENCES["zh"])


@pytest.mark.parametrize("code", list(PREVIEW_SENTENCES))
def test_each_code_speaks_its_own_sentence_and_returns_a_wav(voice_models, sherpa, code):
    make_voice_model(voice_models)
    fake = sherpa()

    data = synthesize_preview(VOICE_ID, code, num_threads=4)

    params, pcm = read_wav(data)
    assert (params.nchannels, params.sampwidth, params.framerate) == (1, 2, 16000)
    assert pcm.size == tone().size
    [tts] = fake.instances
    [spoken] = tts.texts
    if code == "digits":
        assert "2026" in spoken
    if code == "en":
        assert spoken.startswith("welcome to the exhibition hall")


def test_synthesis_runs_on_the_cpu_with_the_server_thread_count(voice_models, sherpa):
    make_voice_model(voice_models)
    fake = sherpa()

    synthesize_preview(VOICE_ID, "zh", num_threads=3)

    [tts] = fake.instances
    assert tts.config.model.provider == "cpu"
    assert tts.config.model.num_threads == 3


def test_loud_output_keeps_headroom(voice_models, sherpa):
    make_voice_model(voice_models)
    sherpa(np.full(3200, 1.45, dtype=np.float32))

    _, pcm = read_wav(synthesize_preview(VOICE_ID, "zh", num_threads=4))

    assert int(np.max(np.abs(pcm))) <= int(0.8801 * 32767)


def test_the_preview_reuses_the_voice_model_the_live_engine_loaded(voice_models, sherpa):
    make_voice_model(voice_models)
    fake = sherpa()
    config = matcha_config()

    create_tts_engine("matcha", config, Parent())
    synthesize_preview(VOICE_ID, "zh", num_threads=config.matcha.num_threads)

    assert len(fake.instances) == 1, "a second copy of the voice model was loaded"
    assert len(fake.instances[0].texts) == 1


def test_an_engine_created_after_the_preview_reuses_its_voice_model(voice_models, sherpa):
    make_voice_model(voice_models)
    fake = sherpa()
    config = matcha_config()

    synthesize_preview(VOICE_ID, "en", num_threads=config.matcha.num_threads)
    create_tts_engine("matcha", config, Parent())

    assert len(fake.instances) == 1


def test_the_preview_waits_for_the_model_lock_the_live_engine_uses(voice_models, sherpa):
    make_voice_model(voice_models)
    fake = sherpa()
    config = Config()
    voice = matcha.load_voice_model(matcha.resolve_voice_model(VOICE_ID), config.matcha.num_threads)
    finished = threading.Event()
    result: list[bytes] = []

    def preview():
        result.append(synthesize_preview(VOICE_ID, "zh", num_threads=config.matcha.num_threads))
        finished.set()

    with voice.lock:
        worker = threading.Thread(target=preview, daemon=True)
        worker.start()
        assert not finished.wait(0.3), "the preview synthesised while another synthesis held the lock"
        assert fake.instances[0].texts == []
    assert finished.wait(5)
    worker.join(5)
    assert len(fake.instances[0].texts) == 1 and result


@pytest.mark.parametrize("sentence", ["", "hello", "zh ", "ZH", "您好", None, 3, ["zh"], "../../etc/passwd"])
def test_only_the_three_codes_are_accepted_and_nothing_is_loaded_otherwise(voice_models, sherpa, sentence):
    make_voice_model(voice_models)
    fake = sherpa()

    with pytest.raises(PreviewError) as caught:
        synthesize_preview(VOICE_ID, sentence, num_threads=4)

    assert caught.value.status == 400
    assert fake.instances == []


@pytest.mark.parametrize("voice_id", ["", "zh-tw-missing", "../zh-tw-fixture", "/etc", None, 7])
def test_a_voice_model_that_is_not_listed_is_a_404_and_nothing_is_loaded(voice_models, sherpa, voice_id):
    make_voice_model(voice_models)
    fake = sherpa()

    with pytest.raises(PreviewError) as caught:
        synthesize_preview(voice_id, "zh", num_threads=4)

    assert caught.value.status == 404
    assert fake.instances == []


def test_a_voice_model_directory_without_its_label_is_not_previewable(voice_models, sherpa):
    model_dir = make_voice_model(voice_models)
    (model_dir / "voice.json").unlink()
    fake = sherpa()

    with pytest.raises(PreviewError) as caught:
        synthesize_preview(VOICE_ID, "zh", num_threads=4)

    assert caught.value.status == 404 and fake.instances == []


def test_a_model_that_cannot_be_loaded_says_why(voice_models, sherpa):
    make_voice_model(voice_models, model_type="vits")
    sherpa()

    with pytest.raises(PreviewError, match="不是 Matcha-TTS 模型") as caught:
        synthesize_preview(VOICE_ID, "zh", num_threads=4)

    assert caught.value.status == 500


def test_silent_synthesis_is_an_error_not_an_empty_file(voice_models, sherpa):
    make_voice_model(voice_models)
    sherpa(np.empty(0, dtype=np.float32))

    with pytest.raises(PreviewError, match="沒有產生") as caught:
        synthesize_preview(VOICE_ID, "zh", num_threads=4)

    assert caught.value.status == 500


def test_audio_over_the_size_limit_is_refused(voice_models, sherpa):
    make_voice_model(voice_models)
    sherpa(np.zeros(int((MAX_PREVIEW_SECONDS + 1) * 16000), dtype=np.float32) + 0.1)

    with pytest.raises(PreviewError, match="上限") as caught:
        synthesize_preview(VOICE_ID, "zh", num_threads=4)

    assert caught.value.status == 500


def test_a_model_with_another_sample_rate_is_written_at_its_own_rate(voice_models, sherpa):
    make_voice_model(voice_models)
    sherpa(tone(0.5), sample_rate=22050)

    params, _ = read_wav(synthesize_preview(VOICE_ID, "zh", num_threads=4))

    assert params.framerate == 22050


def test_cancelling_stops_generation_and_returns_no_audio(voice_models, sherpa):
    make_voice_model(voice_models)
    fake = sherpa()
    stopped = threading.Event()
    stopped.set()
    seen: list[int] = []
    original = types.SimpleNamespace(samples=tone(), sample_rate=16000)

    def generate(self, text, sid=0, speed=1.0, callback=None):
        seen.append(callback(tone(), 0.5))
        return original

    fake.OfflineTts.generate = generate

    with pytest.raises(PreviewError) as caught:
        synthesize_preview(VOICE_ID, "zh", num_threads=4, keep_going=lambda: not stopped.is_set())

    assert seen == [0], "the generation callback must tell sherpa-onnx to stop"
    assert caught.value.status == 408


def test_the_console_shows_the_same_three_sentences_the_server_speaks():
    constants = (Path(__file__).resolve().parents[1] / "web/src/voiceTraining/constants.js").read_text(encoding="utf-8")
    shown = dict(re.findall(r"\{ key: '(\w+)', text: '([^']+)' \}", constants))

    assert shown == PREVIEW_SENTENCES


def test_the_console_keeps_no_copy_of_the_microsoft_clause():
    from src.tts.training.edge_acknowledgement import MSA_CLAUSE

    root = Path(__file__).resolve().parents[1] / "web/src"
    marker = MSA_CLAUSE.text.split(",")[0]
    copies = [
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.suffix in {".js", ".vue"} and marker in path.read_text(encoding="utf-8")
    ]

    assert copies == []
