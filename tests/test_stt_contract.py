# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The STT layer's contract: its DTOs and the in-process adapter behind SttService."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from nova_contracts import CONTRACT_VERSION
from nova_contracts.common import ServiceError, ServiceHealth
from nova_contracts.stt import (
    SttEngineSettings,
    SttPrepareRequest,
    SttService,
    Transcription,
    TranscriptionOptions,
)


def test_a_faster_whisper_result_is_a_transcription():
    result = Transcription.model_validate({
        "text": "你好",
        "language": "zh",
        "language_probability": 0.97,
        "segments": [{"start": 0.0, "end": 0.8, "text": "你好"}],
        "confidence": 0.81,
    })

    assert result.text == "你好"
    assert result.segments[0].end == 0.8
    assert result.confidence == 0.81


def test_a_transcription_without_scores_has_none_for_them():
    result = Transcription(text="hello", language="en")

    assert (result.confidence, result.language_probability, result.segments) == (None, None, ())


def test_transcription_options_only_name_the_supported_languages():
    assert TranscriptionOptions(language="auto").language == "auto"
    with pytest.raises(ValidationError):
        TranscriptionOptions(language="ja")  # type: ignore[arg-type]


def test_engine_settings_reject_an_unknown_device_and_unknown_fields():
    SttEngineSettings(engine="whisper", model_size="small", device="cuda")
    with pytest.raises(ValidationError):
        SttEngineSettings(engine="whisper", model_size="small", device="tpu")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        SttEngineSettings(engine="whisper", model_size="small", device="cpu", path="/etc")  # type: ignore[call-arg]


def test_contract_models_are_immutable():
    settings = SttEngineSettings(engine="whisper", model_size="small", device="cpu")
    with pytest.raises(ValidationError):
        settings.device = "cuda"  # type: ignore[misc]


# --- the in-process adapter (src.asr.adapter) --------------------------------


class Recognizer:
    """A stand-in engine with the BaseASR surface the adapter drives."""

    def __init__(self, settings, *, fails_to_load=False):
        self.settings = settings
        self.fails_to_load = fails_to_load
        self.calls = []

    def ensure_ready(self):
        self.calls.append("load")
        if self.fails_to_load:
            raise RuntimeError("CUDA out of memory")

    def prewarm(self):
        self.calls.append("warm")

    def transcribe(self, audio, *, language=None):
        self.calls.append(("transcribe", audio, language))
        return {"text": f" {self.settings.model_size} heard ", "language": "zh",
                "language_probability": 0.9, "segments": [], "confidence": 0.5}


def stt_service(settings, *, failing=()):
    from src.asr.adapter import InProcessSttService

    built = []

    def create(requested):
        engine = Recognizer(requested, fails_to_load=requested.model_size in failing)
        built.append(engine)
        return engine

    return InProcessSttService(settings, create_engine=create), built


SMALL = SttEngineSettings(engine="whisper", model_size="small", device="cpu")
TURBO = SttEngineSettings(engine="whisper", model_size="turbo", device="cuda")


def test_the_adapter_returns_a_transcription_for_the_requested_language():
    service, built = stt_service(SMALL)

    heard = service.transcribe(b"RIFF", TranscriptionOptions(language="auto"))

    assert heard == Transcription(text=" small heard ", language="zh",
                                  language_probability=0.9, confidence=0.5)
    assert built[0].calls == ["load", ("transcribe", b"RIFF", "auto")]


def test_the_adapter_shares_one_recognizer_between_requests():
    service, built = stt_service(SMALL)

    service.prepare(SttPrepareRequest(warm=False))
    service.transcribe(b"a", TranscriptionOptions(language="zh"))
    service.transcribe(b"b", TranscriptionOptions(language="en"))

    assert len(built) == 1


def test_prepare_warms_the_recognizer_only_when_asked():
    cold, cold_built = stt_service(SMALL)
    warm, warm_built = stt_service(SMALL)

    cold.prepare(SttPrepareRequest(warm=False))
    warm.prepare(SttPrepareRequest(warm=True))

    assert cold_built[0].calls == ["load"]
    assert warm_built[0].calls == ["load", "warm"]


def test_applying_an_engine_switches_to_it_once_it_has_loaded():
    service, built = stt_service(SMALL)
    service.prepare(SttPrepareRequest(warm=False))

    assert service.apply_engine(TURBO) == TURBO
    heard = service.transcribe(b"a", TranscriptionOptions(language="zh"))

    assert heard.text == " turbo heard "
    assert built[1].settings == TURBO and built[1].calls[0] == "load"


def test_an_engine_that_fails_to_load_is_refused_and_the_current_one_kept():
    service, _ = stt_service(SMALL, failing={"turbo"})

    with pytest.raises(ServiceError, match="CUDA out of memory"):
        service.apply_engine(TURBO)

    assert service.transcribe(b"a", TranscriptionOptions(language="zh")).text == " small heard "


def test_health_reports_the_contract_version_and_whether_the_recognizer_is_loaded():
    service, _ = stt_service(SMALL)

    before = service.health()
    service.prepare(SttPrepareRequest(warm=False))
    after = service.health()

    assert before == ServiceHealth(contract_version=CONTRACT_VERSION, engine="whisper", ready=False)
    assert after.ready is True


def test_the_adapter_implements_the_stt_service_protocol():
    service, _ = stt_service(SMALL)

    assert isinstance(service, SttService)
