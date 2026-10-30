# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Fun-ASR-Nano-2512: weights, the loopback service, its process and the Nova engine."""

from __future__ import annotations

import io
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import requests
import soundfile as sf

from scripts import fun_asr_nano_server as server
from scripts import fun_asr_nano_weights
from src.asr import factory
from src.asr import fun_asr_nano_service as service
from src.asr.engines.funasr import FunASR, pcm16_16k
from src.config.schema import Config


def wav(samples: np.ndarray, rate: int) -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, samples, rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


def tone(seconds: float, rate: int, channels: int = 1) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    mono = (0.25 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    return mono if channels == 1 else np.stack([mono] * channels, axis=1)


def asr_config(**values) -> SimpleNamespace:
    settings = {"device": "cpu", "output_script": "traditional-tw", "language": "auto", **values}
    return SimpleNamespace(asr=SimpleNamespace(**settings))


# ------------------------------------------------------------------- weights


def test_fun_asr_nano_download_is_pinned_and_complete():
    (source,) = fun_asr_nano_weights.MODELS
    assert source.repo == "FunAudioLLM/Fun-ASR-Nano-2512"
    assert len(source.revision) == 40 and int(source.revision, 16) >= 0
    assert all(len(digest) == 64 and int(digest, 16) >= 0 for digest in source.files.values())
    # Everything funasr's FunASRNano loader reads from a local model folder.
    assert {
        "config.yaml", "configuration.json", "model.pt", "multilingual.tiktoken",
        "Qwen3-0.6B/config.json", "Qwen3-0.6B/tokenizer.json", "Qwen3-0.6B/tokenizer_config.json",
        "Qwen3-0.6B/vocab.json", "Qwen3-0.6B/merges.txt",
    } <= set(source.files)
    # No model code is fetched: the model class comes from the pinned funasr package.
    assert not any(name.endswith(".py") for name in source.files)


def test_service_model_folder_is_where_the_download_puts_it():
    (source,) = fun_asr_nano_weights.MODELS
    assert service.model_dir(service.DEFAULT_MODEL) == fun_asr_nano_weights.ROOT / source.local_dir
    assert set(service.REQUIRED_MODEL_FILES) <= set(source.files)
    assert Path(server.DEFAULT_MODEL_DIR) == service.model_dir(service.DEFAULT_MODEL)


def test_fun_asr_nano_download_passes_pinned_revision_and_files(tmp_path):
    calls = []
    fun_asr_nano_weights.download(tmp_path, snapshot=lambda repo, **kwargs: calls.append((repo, kwargs)))
    (source,) = fun_asr_nano_weights.MODELS
    assert calls == [(source.repo, {
        "revision": source.revision,
        "local_dir": str(tmp_path / source.local_dir),
        "allow_patterns": sorted(source.files),
    })]


def test_fun_asr_nano_check_fails_when_weights_are_missing(tmp_path):
    with pytest.raises(SystemExit, match=r"model\.pt \(missing\)"):
        fun_asr_nano_weights.main(["--check", "--root", str(tmp_path)])


# -------------------------------------------------------------------- server


class FakeModel:
    def __init__(self, text="开放时间早上九点"):
        self.text = text
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return [{"key": "k", "text": self.text}]


def recognizer(model=None, converter=None):
    from opencc import OpenCC

    return server.Recognizer(model or FakeModel(), model_dir="/m", device="cpu", requested_device="auto",
                             converter=converter or OpenCC("s2twp").convert)


def pcm(samples: np.ndarray) -> bytes:
    return (samples * 32767).astype("<i2").tobytes()


def test_server_converts_output_to_taiwan_traditional():
    model = FakeModel("软件和鼠标")
    result = recognizer(model).recognize(pcm(tone(0.5, 16000)))
    assert result == {"text": "軟體和滑鼠", "language": "zh"}
    (call,) = model.calls
    waveform = call["input"][0]
    assert waveform.dtype == np.float32 and waveform.shape == (8000,)
    assert call["language"] is None and call["itn"] is True


def test_server_can_keep_simplified_and_reports_english():
    assert recognizer(FakeModel("软件")).recognize(b"\0\0", script="simplified")["text"] == "软件"
    english = recognizer(FakeModel("Open from nine to five.")).recognize(b"\0\0", language="en")
    assert english == {"text": "Open from nine to five.", "language": "en"}


def test_server_passes_the_requested_language_to_the_prompt():
    model = FakeModel()
    recognizer(model).recognize(b"\0\0", language="zh")
    assert model.calls[0]["language"] == "中文"


@pytest.mark.parametrize("body, options, message", [
    (b"", {}, "沒有音訊"),
    (b"\0", {}, "16-bit"),
    (b"\0\0", {"language": "ja"}, "語言"),
    (b"\0\0", {"script": "hk"}, "輸出文字"),
])
def test_server_rejects_malformed_requests(body, options, message):
    model = FakeModel()
    with pytest.raises(server.RequestError, match=message):
        recognizer(model).recognize(body, **options)
    assert model.calls == []


@pytest.fixture
def http_service():
    model = FakeModel("软件")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(recognizer(model)))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", model
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_routes_serve_health_and_recognition(http_service):
    url, _ = http_service
    health = requests.get(f"{url}/health", timeout=5).json()
    assert health["family"] == "fun-asr-nano"
    assert health["model_dir"] == "/m" and health["requested_device"] == "auto"
    assert service.recognize(url, pcm(tone(0.2, 16000)), language="auto",
                             script="traditional-tw") == {"text": "軟體", "language": "zh"}


def test_http_rejects_oversized_and_invalid_audio(http_service, monkeypatch):
    url, model = http_service
    monkeypatch.setattr(server, "MAX_BODY_BYTES", 4)
    assert requests.post(f"{url}/recognize", data=b"\0" * 6, timeout=5).status_code == 413
    assert requests.get(f"{url}/other", timeout=5).status_code == 404
    with pytest.raises(RuntimeError, match="16-bit"):
        service.recognize(url, b"\0", language="auto", script="traditional-tw")
    assert model.calls == []


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "example.com"])
def test_server_binds_only_to_loopback(host, tmp_path):
    (tmp_path / "model.pt").write_bytes(b"x")
    with pytest.raises(SystemExit):
        server.parse_args(["--host", host, "--model_dir", str(tmp_path)])
    assert server.parse_args(["--host", "127.0.0.1", "--model_dir", str(tmp_path)]).host == "127.0.0.1"


def test_server_loads_bundled_model_class_without_remote_code(tmp_path, monkeypatch):
    auto_model = MagicMock()
    # Only this entry is swapped: restoring all of sys.modules would unload torch.
    monkeypatch.setitem(sys.modules, "funasr", SimpleNamespace(AutoModel=auto_model))
    with patch.object(server, "resolve_device", return_value="cpu"):
        loaded = server.load_recognizer(tmp_path, "cpu")
    auto_model.assert_called_once_with(model=str(tmp_path), device="cpu", disable_update=True,
                                       trust_remote_code=False)
    assert loaded.health()["device"] == "cpu"


# ------------------------------------------------------------------- process


def model_folder(root: Path) -> Path:
    folder = root / "funasr" / service.DEFAULT_MODEL
    for name in service.REQUIRED_MODEL_FILES:
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(b"x")
    return folder


@pytest.fixture
def installed(tmp_path, monkeypatch):
    python = tmp_path / "venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("")
    monkeypatch.setenv("FUN_ASR_NANO_PYTHON", str(python))
    monkeypatch.setattr(service, "MODELS_ROOT", tmp_path / "models")
    folder = model_folder(tmp_path / "models")
    return SimpleNamespace(python=python, folder=folder)


def test_models_resolve_only_from_the_server_managed_list(installed):
    assert service.resolve_model("Fun-ASR-Nano-2512") == "Fun-ASR-Nano-2512"
    # Saved settings from before Fun-ASR-Nano still load.
    assert service.resolve_model("paraformer-zh") == "Fun-ASR-Nano-2512"
    for name in ("/etc", "../Fun-ASR-Nano-2512", "funasr/Fun-ASR-Nano-2512"):
        with pytest.raises(ValueError):
            service.resolve_model(name)


def test_availability_reports_missing_venv_or_weights(installed, monkeypatch, tmp_path):
    assert service.unavailable_reason() == ""
    assert service.model_ready()
    (installed.folder / "model.pt").unlink()
    assert not service.model_ready()
    assert "fun_asr_nano_weights.py" in service.unavailable_reason()
    monkeypatch.setenv("FUN_ASR_NANO_PYTHON", str(tmp_path / "missing/python"))
    assert "setup-fun-asr-nano.sh" in service.unavailable_reason()


def test_ensure_server_reuses_a_healthy_matching_service(installed):
    health = {"family": "fun-asr-nano", "model_dir": str(installed.folder), "requested_device": "cpu"}
    with patch.object(service, "_health_payload", return_value=health), \
            patch.object(service.subprocess, "Popen") as popen:
        assert service.ensure_server(model="Fun-ASR-Nano-2512", device="cpu") == "http://127.0.0.1:50010"
    popen.assert_not_called()


def test_ensure_server_starts_the_owned_loopback_process(installed, tmp_path, monkeypatch):
    monkeypatch.setattr(service, "LOG_PATH", tmp_path / "logs/fun-asr-nano-server.log")
    payloads = iter([None, None, {"family": "fun-asr-nano", "model_dir": str(installed.folder),
                                  "requested_device": "cuda"}])
    process = MagicMock()
    process.poll.return_value = None
    with patch.object(service, "_health_payload", side_effect=lambda _url: next(payloads)), \
            patch.object(service, "_stop_stale_listener") as stale, \
            patch.object(service.subprocess, "Popen", return_value=process) as popen, \
            patch.object(service.time, "sleep"):
        url = service.ensure_server(model="Fun-ASR-Nano-2512", device="cuda")
    assert url == "http://127.0.0.1:50010"
    stale.assert_called_once_with(50010)
    command = popen.call_args.args[0]
    assert command == [str(installed.python), str(service.SERVER_SCRIPT), "--host", "127.0.0.1",
                       "--port", "50010", "--model_dir", str(installed.folder), "--device", "cuda"]
    assert popen.call_args.kwargs["start_new_session"] is True
    service.shutdown_fun_asr_server()
    process.terminate.assert_called_once()


def test_ensure_server_reports_a_crashed_start(installed, tmp_path, monkeypatch):
    monkeypatch.setattr(service, "LOG_PATH", tmp_path / "server.log")
    process = MagicMock()
    process.poll.return_value = 1
    process.returncode = 1
    with patch.object(service, "_health_payload", return_value=None), \
            patch.object(service, "_stop_stale_listener"), \
            patch.object(service.subprocess, "Popen", return_value=process):
        with pytest.raises(RuntimeError, match="server.log"):
            service.ensure_server(model="Fun-ASR-Nano-2512", device="cpu")


def test_ensure_server_refuses_non_loopback_hosts(installed):
    with pytest.raises(ValueError, match="loopback"):
        service.ensure_server(model="Fun-ASR-Nano-2512", device="cpu", host="0.0.0.0")


# -------------------------------------------------------------------- engine


def test_engine_starts_the_service_only_when_loaded(installed):
    with patch.object(service, "ensure_server", return_value="http://127.0.0.1:50010") as ensure:
        engine = factory.create_asr_engine("funasr", config=asr_config(), model_size="paraformer-zh")
        ensure.assert_not_called()
        engine.ensure_ready()
    ensure.assert_called_once_with(model="Fun-ASR-Nano-2512", device="cpu")
    assert engine.get_info()["model_name"] == "Fun-ASR-Nano-2512"


def test_engine_sends_16k_mono_pcm_and_returns_the_service_text():
    engine = FunASR(config=asr_config(language="zh", output_script="simplified"))
    engine.url = "http://127.0.0.1:50010"
    engine._initialized = True
    with patch.object(service, "recognize", return_value={"text": "软件", "language": "zh"}) as recognize:
        assert engine.transcribe(wav(tone(1.0, 16000), 16000), language="auto")["text"] == "软件"
        engine.transcribe(wav(tone(1.0, 16000), 16000))
    first, second = recognize.call_args_list
    assert first.args[0] == "http://127.0.0.1:50010"
    assert len(first.args[1]) == 32000
    assert first.kwargs == {"language": "auto", "script": "simplified"}
    # Without a per-call option the configured /asr upload language applies.
    assert second.kwargs["language"] == "zh"
    assert engine.supports_language_options is True


def test_audio_is_resampled_and_downmixed_to_16k_pcm16():
    stereo_48k = wav(tone(0.5, 48000, channels=2), 48000)
    converted = np.frombuffer(pcm16_16k(stereo_48k), dtype="<i2")
    assert abs(converted.size - 8000) <= 32
    assert 0.1 < np.abs(converted).max() / 32768 < 0.3
    mono_16k = tone(0.25, 16000)
    exact = np.frombuffer(pcm16_16k(wav(mono_16k, 16000)), dtype="<i2")
    assert exact.size == 4000


def test_engine_rejects_unknown_devices_and_scripts():
    with pytest.raises(ValueError):
        FunASR(config=asr_config(device="tpu"))
    with pytest.raises(ValueError):
        FunASR(config=asr_config(output_script="hk"))


# ------------------------------------------------------------------ settings


def test_settings_offer_fun_asr_nano_from_the_service(installed):
    from src.server.runtime_settings import speech_snapshot

    stt = speech_snapshot(Config())["stt"]
    funasr = next(item for item in stt["engines"] if item["id"] == "funasr")
    assert "Fun-ASR-Nano" in funasr["label"]
    assert funasr["available"] is True
    assert stt["models_by_engine"]["funasr"] == ["Fun-ASR-Nano-2512"]
    assert stt["local_model_ready"] is True
    assert "paraformer" not in json.dumps(stt)


def test_settings_report_a_missing_service_venv(installed, monkeypatch, tmp_path):
    from src.server.runtime_settings import speech_snapshot

    monkeypatch.setenv("FUN_ASR_NANO_PYTHON", str(tmp_path / "missing/python"))
    funasr = next(item for item in speech_snapshot(Config())["stt"]["engines"] if item["id"] == "funasr")
    assert funasr["available"] is False
    assert "setup-fun-asr-nano.sh" in funasr["message"]


def test_applying_fun_asr_rejects_unlisted_models(installed):
    from src.server.runtime_settings import SettingsError, apply_stt_settings

    with pytest.raises(SettingsError, match="模型"):
        apply_stt_settings(Config(), {"type": "funasr", "model_size": "/etc/passwd"}, session_count=0)


def test_applying_fun_asr_over_saved_paraformer_uses_fun_asr_nano(installed):
    from src.server import runtime_settings

    config = Config()
    config.asr.model_size = "paraformer-zh"
    with patch.object(runtime_settings, "create_asr_engine") as create, \
            patch.object(runtime_settings, "activate_asr_engine"), \
            patch.object(runtime_settings, "persist_runtime_overrides"):
        runtime_settings.apply_stt_settings(config, {"type": "funasr"}, session_count=0)
    assert create.call_args.kwargs["model_size"] == "Fun-ASR-Nano-2512"
    assert config.asr.model_size == "Fun-ASR-Nano-2512"


def test_switching_back_to_whisper_stops_the_fun_asr_service(installed):
    from src.server import runtime_settings

    candidate = MagicMock()
    with patch.object(runtime_settings, "create_asr_engine", return_value=candidate), \
            patch.object(runtime_settings, "activate_asr_engine"), \
            patch.object(runtime_settings, "persist_runtime_overrides"), \
            patch.object(service, "stop_server") as stop:
        runtime_settings.apply_stt_settings(
            Config(), {"type": "funasr", "model_size": "Fun-ASR-Nano-2512"}, session_count=0)
        stop.assert_not_called()
        runtime_settings.apply_stt_settings(Config(), {"type": "whisper", "model_size": "small"},
                                            session_count=0)
    stop.assert_called_once_with()


def test_english_conversations_accept_fun_asr():
    from src.server.conversations import check_language_support

    config = Config()
    config.asr.type = "funasr"
    config.tts.type = "edgetts"
    check_language_support(config, "en-US")
