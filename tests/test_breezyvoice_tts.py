# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""BreezyVoice: weights, text frontend, owned-server loading and the Nova engine."""

from __future__ import annotations

import hashlib
import io
import zipfile
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf

from src.config.schema import Config
from src.server.runtime_settings import (
    SettingsError,
    TTS_ENGINE_META,
    apply_tts_settings,
    speech_snapshot,
)
from src.tts import cosyvoice_runtime as runtime
from src.tts import voice_library
from src.tts.base import State
from src.tts.factory import create_tts_engine

from scripts import breezyvoice_frontend as frontend
from scripts import breezyvoice_weights

WORD_UTILS = '''from collections import Counter, defaultdict

always_augment_chars = {"長"}

char2phn = {
    "長": ["ㄔㄤ2", "ㄓㄤ3"],
    "和": ["ㄏㄜ2", "ㄏㄢ4", "ㄏㄨㄛ4"],
    "垃": ["ㄌㄚ1", "ㄌㄜ4"],
    "天": ["ㄊㄧㄢ1"],
}
char2phn = defaultdict(list, char2phn)
word_to_dataset_frequency = Counter({"天": 90000, "和": 50000, "長": 20000, "垃": 300})
__import__("os").environ["BREEZY_TABLES_EXECUTED"] = "1"
'''


def wav_bytes(seconds: float = 1.0, rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    t = np.arange(int(seconds * rate)) / rate
    sf.write(buffer, (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), rate, format="WAV")
    return buffer.getvalue()


@pytest.fixture
def tables(tmp_path):
    path = tmp_path / "word_utils.py"
    path.write_text(WORD_UTILS, "utf-8")
    return frontend.load_reading_tables(path)


@pytest.fixture
def voices(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_library, "VOICES_ROOT", tmp_path / "voices")
    return tmp_path / "voices"


def add_voice(tmp_path, transcript: str = "") -> str:
    source = tmp_path / "speaker.wav"
    source.write_bytes(wav_bytes())
    return voice_library.add_voice(source, "speaker", transcript=transcript)["id"]


def breezy_dir(models: Path, name: str = "BreezyVoice") -> Path:
    directory = models / name
    directory.mkdir(parents=True)
    (directory / "cosyvoice.yaml").write_text("")
    (directory / "word_utils.py").write_text(WORD_UTILS, "utf-8")
    return directory


# ---------------------------------------------------------------- weights


def test_every_breezyvoice_download_is_pinned():
    for source in breezyvoice_weights.MODELS:
        assert len(source.revision) == 40 and int(source.revision, 16) >= 0, source.repo
        assert all(len(digest) == 64 for digest in source.files.values()), source.repo
    for item in breezyvoice_weights.URL_FILES:
        assert "/d592c9d3e8927a0f53f68616387060dcd32a05ea/" in item.url
        assert len(item.sha256) == 64
    names = {name for source in breezyvoice_weights.MODELS for name in source.files}
    assert {"llm.pt", "flow.pt", "hift.pt", "cosyvoice.yaml", "G2PWModel-v2-onnx.zip", "vocab.txt"} <= names


def test_url_file_with_wrong_checksum_is_not_kept(tmp_path):
    item = breezyvoice_weights.UrlFile("https://example.invalid/x", "models/x/word_utils.py",
                                       hashlib.sha256(b"expected").hexdigest())

    def fetch(url, destination):
        destination.write_bytes(b"tampered")

    with pytest.raises(SystemExit, match="sha256 mismatch"):
        breezyvoice_weights.download(tmp_path, models=[], url_files=[item], snapshot=lambda *a, **k: None,
                                     fetch=fetch)
    assert not (tmp_path / item.path).exists()
    assert list((tmp_path / "models/x").iterdir()) == []

    breezyvoice_weights.download(tmp_path, models=[], url_files=[item], snapshot=lambda *a, **k: None,
                                 fetch=lambda url, destination: destination.write_bytes(b"expected"))
    assert breezyvoice_weights.verify_all(tmp_path, models=[], url_files=[item]) == []


def test_g2pw_archive_cannot_write_outside_its_folder(tmp_path):
    archive = tmp_path / breezyvoice_weights.G2PW_ARCHIVE
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("G2PWModel/g2pw.onnx", b"onnx")
        bundle.writestr("../../escape.txt", b"x")
    with pytest.raises(SystemExit, match="unexpected entry"):
        breezyvoice_weights.unpack_g2pw(tmp_path)
    assert not (tmp_path / "models" / "escape.txt").exists()

    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("G2PWModel/g2pw.onnx", b"onnx")
    assert (breezyvoice_weights.unpack_g2pw(tmp_path) / "g2pw.onnx").read_bytes() == b"onnx"


# ---------------------------------------------------------------- text frontend


def test_reading_tables_are_parsed_without_running_the_file(tables, monkeypatch):
    monkeypatch.delenv("BREEZY_TABLES_EXECUTED", raising=False)
    assert tables.readings["和"] == ["ㄏㄜ2", "ㄏㄢ4", "ㄏㄨㄛ4"]
    assert tables.frequency["天"] == 90000
    assert tables.always_annotate == frozenset({"長"})
    import os

    assert "BREEZY_TABLES_EXECUTED" not in os.environ


def test_rare_characters_and_uncommon_readings_get_zhuyin(tables):
    text = "天和垃長"
    readings = ["ㄊㄧㄢ1", "ㄏㄢ4", "ㄌㄜ4", "ㄓㄤ3"]
    assert frontend.annotate_readings(text, readings, tables) == "天和垃[:ㄌㄜ4]長[:ㄓㄤ3]"
    # 和 is frequent (>= 10000), so even its Taiwan conjunction reading stays plain;
    # a less frequent character with a non-default reading is spelled out.
    low = frontend.ReadingTables(frequency=Counter({**tables.frequency, "和": 2000}),
                                 readings=tables.readings, always_annotate=tables.always_annotate)
    assert frontend.annotate_readings("和", ["ㄏㄢ4"], low) == "和[:ㄏㄢ4]"
    assert frontend.annotate_readings("和", ["ㄏㄜ2"], low) == "和"


def test_existing_hints_and_missing_predictions_are_left_alone(tables):
    assert frontend.annotate_readings("垃[:ㄌㄚ1]", ["ㄌㄜ4", None, None, None, None, None, None], tables) \
        == "垃[:ㄌㄚ1]"
    assert frontend.annotate_readings("垃長", [None, None], tables) == "垃長"


def test_frontend_prepares_text_with_g2pw_readings(tmp_path):
    directory = breezy_dir(tmp_path / "models")
    calls = []

    def converter(text):
        calls.append(text)
        return [["ㄌㄜ4" if char == "垃" else None for char in text]]

    prepared = frontend.BreezyVoiceFrontend(directory, normalize=str.upper, converter=converter)
    assert prepared.prepare("  垃ok ") == "垃[:ㄌㄜ4]OK"
    assert prepared.prepare("   ") == ""
    assert calls == ["垃OK"]


def test_frontend_requires_the_downloaded_g2pw_model(tmp_path):
    directory = breezy_dir(tmp_path / "models")
    with pytest.raises(FileNotFoundError, match="breezyvoice_weights"):
        frontend.BreezyVoiceFrontend(directory)


def test_top_k_sampling_only_returns_top_k_ids():
    torch = pytest.importorskip("torch")
    scores = torch.tensor([10.0, 9.0, -50.0, -50.0, -50.0])
    picks = {frontend.top_k_sampling(scores, [], 2) for _ in range(50)}
    assert picks <= {0, 1}


def test_g2pw_onnx_session_is_pinned_to_cpu():
    created = {}

    def session(path, sess_options=None, **kwargs):
        created.update(path=path, options=sess_options, **kwargs)
        return "session"

    module = SimpleNamespace(onnxruntime=SimpleNamespace(InferenceSession=session))
    options = SimpleNamespace(intra_op_num_threads=2)
    with frontend.cpu_onnx_sessions(module, threads=6):
        assert module.onnxruntime.InferenceSession("g2pw.onnx", sess_options=options) == "session"
    assert created["providers"] == ["CPUExecutionProvider"]
    assert options.intra_op_num_threads == 6
    assert module.onnxruntime.InferenceSession is session


def test_breezyvoice_model_loads_with_yaml_overrides_only_during_construction(tmp_path):
    seen = []

    def load_hyperpyyaml(stream, overrides=None, **kwargs):
        seen.append((overrides, kwargs))
        return {}

    class CosyVoice:
        sample_rate = 22050

        def __init__(self, model_dir):
            self.model_dir = model_dir
            self.frontend = SimpleNamespace(feat_extractor=None, device="cpu")
            cli.load_hyperpyyaml("yaml")

    pytest.importorskip("torch")
    cli = SimpleNamespace(load_hyperpyyaml=load_hyperpyyaml, CosyVoice=CosyVoice)
    model = frontend.load_breezyvoice_model(tmp_path, cli=cli, load_wav=lambda path, rate: None)
    assert model.model_dir == str(tmp_path)
    assert seen == [(frontend.YAML_OVERRIDES, {"overrides_must_match": False})]
    assert "breezyvoice_frontend.top_k_sampling" in frontend.YAML_OVERRIDES
    assert cli.load_hyperpyyaml is load_hyperpyyaml


def test_prompt_mel_is_computed_at_the_model_rate():
    torch = pytest.importorskip("torch")
    loaded = []

    def load_wav(path, rate):
        loaded.append((path, rate))
        return torch.zeros(1, rate)

    def mel(speech):
        return torch.zeros(1, 80, speech.shape[1] // 256)

    model = SimpleNamespace(sample_rate=22050,
                            frontend=SimpleNamespace(feat_extractor=mel, device="cpu"))
    frontend.match_prompt_feature_rate(model, load_wav)
    feat, length = model.frontend._extract_speech_feat("prompt.wav")
    assert loaded == [("prompt.wav", 22050)]
    assert tuple(feat.shape) == (1, 22050 // 256, 80)
    assert length.tolist() == [22050 // 256]


# ---------------------------------------------------------------- models/ catalog


def test_breezyvoice_models_are_listed_by_their_reading_tables(tmp_path, monkeypatch):
    models = tmp_path / "models"
    breezy_dir(models)
    plain = models / "CosyVoice-300M"
    plain.mkdir()
    (plain / "cosyvoice.yaml").write_text("")
    monkeypatch.setattr(runtime, "MODELS_ROOT", models)
    assert runtime.local_models() == [{"id": "BreezyVoice"}]
    assert runtime.resolve_model_dir("") == models / "BreezyVoice"
    assert runtime.resolve_model_dir("BreezyVoice") == models / "BreezyVoice"
    with pytest.raises(FileNotFoundError):
        runtime.resolve_model_dir("CosyVoice-300M")


def test_missing_default_breezyvoice_model_names_the_download_script(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "MODELS_ROOT", tmp_path / "models")
    with pytest.raises(FileNotFoundError, match="breezyvoice_weights.py"):
        runtime.resolve_model_dir("")


# ---------------------------------------------------------------- voice library transcript


def test_voice_library_keeps_a_cleaned_transcript(voices, tmp_path):
    voice = add_voice(tmp_path, transcript="  在密碼學中，\x00加密是方法。 ")
    assert voice_library.voice_transcript(voice) == "在密碼學中，加密是方法。"
    assert voice_library.list_voices()[0]["transcript"] == "在密碼學中，加密是方法。"
    assert voice_library.voice_transcript("") == ""


# ---------------------------------------------------------------- engine


def engine(ref_file: str = "", ref_text: str = "", parent=None):
    config = SimpleNamespace(
        audio=SimpleNamespace(fps=50),
        tts=SimpleNamespace(type="breezyvoice", ref_file=ref_file, ref_text=ref_text,
                            tts_server="http://127.0.0.1:50000"),
    )
    return create_tts_engine("breezyvoice", config, parent or MagicMock())


def test_engine_uses_library_audio_and_transcript_for_zero_shot(voices, tmp_path):
    voice = add_voice(tmp_path, transcript="參考逐字稿。")
    tts = engine(ref_file=voice)
    assert tts._prompt_text() == "參考逐字稿。"
    assert tts._tts_request("你好。", tts._prompt_text()) == (
        "inference_zero_shot", {"tts_text": "你好。", "prompt_text": "參考逐字稿。"})
    # A stale profile-level override never replaces the library transcript.
    assert engine(ref_file=voice, ref_text="設定的逐字稿")._prompt_text() == "參考逐字稿。"


def test_engine_refuses_without_library_voice_or_transcript(voices, tmp_path):
    with pytest.raises(FileNotFoundError, match="音訊庫"):
        engine()._prompt_wav()
    voice = add_voice(tmp_path)
    with pytest.raises(ValueError, match="逐字稿"):
        engine(ref_file=voice)._prompt_text()
    with pytest.raises(ValueError, match="逐字稿"):
        engine(ref_file=voice, ref_text="覆寫的逐字稿")._prompt_text()


def test_engine_resamples_breezyvoice_22050_hz_audio_per_fragment(voices, tmp_path):
    frames = []
    parent = MagicMock()
    parent.put_audio_frame.side_effect = lambda frame, event: frames.append((frame, event))
    tts = engine(parent=parent)
    tts.state = State.RUNNING
    one_second = (np.zeros(22050, dtype=np.int16)).tobytes()
    assert tts.stream_tts(iter([one_second]), ("你好。", {}))
    assert tts.SOURCE_SAMPLE_RATE == 22050
    samples = sum(len(frame) for frame, _ in frames)
    assert abs(samples - tts.sample_rate) <= tts.chunk


# ---------------------------------------------------------------- settings


def test_breezyvoice_is_a_selectable_local_engine():
    assert TTS_ENGINE_META["breezyvoice"]["label"] == "BreezyVoice"
    snapshot = speech_snapshot(Config())["tts"]
    assert "breezyvoice" in {item["id"] for item in snapshot["engines"]}


def test_apply_requires_a_library_voice_with_transcript(voices, tmp_path):
    voice = add_voice(tmp_path)
    with patch("src.server.runtime_settings._engine_available", return_value=True), \
            patch("src.tts.cosyvoice_runtime.ensure_server") as ensure:
        with pytest.raises(SettingsError, match="音訊庫"):
            apply_tts_settings(Config(), {"type": "breezyvoice"}, session_count=0)
        with pytest.raises(SettingsError, match="逐字稿"):
            apply_tts_settings(Config(), {"type": "breezyvoice", "ref_file": voice}, session_count=0)
    ensure.assert_not_called()


def test_apply_starts_the_owned_server_for_breezyvoice(voices, tmp_path):
    voice = add_voice(tmp_path, transcript="參考逐字稿。")
    config = Config()
    with patch("src.server.runtime_settings._engine_available", return_value=True), \
            patch("src.tts.cosyvoice_runtime.ensure_server", return_value="http://127.0.0.1:50000") as ensure, \
            patch("src.server.runtime_settings._preview_tts", return_value="data:audio/wav;base64,dA==") as preview, \
            patch("src.server.runtime_settings.persist_runtime_overrides"):
        apply_tts_settings(config, {"type": "breezyvoice", "ref_file": voice}, session_count=0)
    ensure.assert_called_once_with(model_dir="", host="127.0.0.1", port=50000)
    assert preview.call_args.kwargs["ref_file"] == voice
    assert config.tts.type == "breezyvoice"
    assert config.tts.ref_file == voice
    assert config.tts.tts_server == "http://127.0.0.1:50000"


def test_engine_reports_http_errors_and_empty_audio_after_notifying(voices, tmp_path):
    voice = add_voice(tmp_path, transcript="參考逐字稿。")
    for status, chunks, message in ((400, [], "HTTP 400"), (200, [], "no decodable audio")):
        parent = MagicMock()
        tts = engine(ref_file=voice, parent=parent)
        tts.state = State.RUNNING
        response = MagicMock(status_code=status, text="bad prompt",
                             iter_content=lambda chunk_size=None, chunks=chunks: iter(chunks))
        with patch("src.tts.engines.breezyvoice.prepare_prompt_wav", side_effect=lambda path: path), \
                patch("src.tts.engines.breezyvoice.requests.post", return_value=response) as post:
            with pytest.raises(RuntimeError, match=message):
                tts.txt_to_audio(("你好", {"turn_id": "t1"}))
        assert post.call_args.args[0] == "http://127.0.0.1:50000/inference_zero_shot"
        assert post.call_args.kwargs["timeout"]
        parent.notify_fragment_synthesis_failed.assert_called_once_with(
            {"turn_id": "t1"}, "tts_exhausted_before_audio")
