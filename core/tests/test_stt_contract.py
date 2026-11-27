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
    TranscriptionSegment,
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


# --- the in-process adapter (nova_stt.adapter) --------------------------------


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
    from nova_stt.adapter import InProcessSttService

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


# --- the fake engine, selected through settings like any engine --------------
#
# ``fake`` answers every utterance with one fixed text. It is not a product
# engine, so the console catalog does not list it; settings (config.yaml's
# ``asr:`` section) select it, with ``model_size`` carrying the text to return.

HELLO = SttEngineSettings(engine="fake", model_size="你好", device="cpu")
GOODBYE = SttEngineSettings(engine="fake", model_size="再見", device="cpu")
BROKEN = SttEngineSettings(engine="fake", model_size="不能載入", device="cpu")
WAV = b"RIFF....WAVE"  # the fake never decodes its input
ZH = TranscriptionOptions(language="zh")


def fake_stt_service(settings, *, configure=lambda engine, requested: None):
    """The real adapter and factory; ``configure`` may adjust each engine built."""
    from nova_stt.adapter import InProcessSttService
    from nova_stt.factory import create_asr_engine

    def create(requested):
        engine = create_asr_engine(requested)
        configure(engine, requested)
        return engine

    return InProcessSttService(settings, create_engine=create)


def refuse_to_load_broken(engine, requested):
    if requested == BROKEN:
        def refuse():
            raise RuntimeError("CUDA out of memory")
        engine._load_model = refuse


def test_the_fake_engine_answers_every_utterance_with_the_configured_text():
    from nova_stt.adapter import create_stt_service

    service = create_stt_service(HELLO)

    heard = service.transcribe(WAV, ZH)

    assert heard == Transcription(
        text="你好", language="zh", language_probability=1.0, confidence=1.0,
        segments=(TranscriptionSegment(start=0.0, end=0.0, text="你好"),))
    assert service.transcribe(b"other audio", ZH) == heard


def test_the_fake_engine_reports_the_requested_language_and_picks_chinese_for_auto():
    service = fake_stt_service(HELLO)

    languages = {requested: service.transcribe(WAV, TranscriptionOptions(language=requested)).language
                 for requested in ("zh", "en", "auto")}

    assert languages == {"zh": "zh", "en": "en", "auto": "zh"}


def test_an_empty_fixed_text_is_a_silent_utterance():
    service = fake_stt_service(SttEngineSettings(engine="fake", model_size=""))

    heard = service.transcribe(WAV, TranscriptionOptions(language="auto"))

    assert heard.text == "" and heard.segments == ()


def test_the_fake_engine_is_loaded_and_warmed_through_prepare_and_reported_by_health():
    service = fake_stt_service(HELLO)

    before = service.health()
    service.prepare(SttPrepareRequest(warm=True))
    service.prepare(SttPrepareRequest(warm=True))
    after = service.health()

    assert before == ServiceHealth(contract_version=CONTRACT_VERSION, engine="fake", ready=False)
    assert after == ServiceHealth(contract_version=CONTRACT_VERSION, engine="fake", ready=True)


def test_switching_between_fake_engines_answers_with_the_new_text():
    service = fake_stt_service(HELLO)
    service.prepare(SttPrepareRequest(warm=False))

    assert service.apply_engine(GOODBYE) == GOODBYE

    assert service.transcribe(WAV, ZH).text == "再見"
    assert service.health().engine == "fake"


def test_an_unknown_engine_is_refused_and_the_current_one_kept():
    service = fake_stt_service(HELLO)

    with pytest.raises(ServiceError, match="nonexistent"):
        service.apply_engine(SttEngineSettings(engine="nonexistent", model_size="x"))

    assert service.transcribe(WAV, ZH).text == "你好"
    assert service.health().engine == "fake"


def test_a_fake_engine_that_fails_to_load_is_refused_and_the_current_one_kept():
    service = fake_stt_service(HELLO, configure=refuse_to_load_broken)
    service.prepare(SttPrepareRequest(warm=False))
    before = service.health()

    with pytest.raises(ServiceError, match="CUDA out of memory"):
        service.apply_engine(BROKEN)

    assert service.health() == before
    assert service.transcribe(WAV, ZH).text == "你好"


def test_a_request_during_a_switch_is_answered_by_the_current_recognizer():
    import threading

    loading, release = threading.Event(), threading.Event()

    def hold_goodbye_while_loading(engine, requested):
        if requested == GOODBYE:
            real_load = engine._load_model

            def slow_load():
                loading.set()
                assert release.wait(5)
                real_load()
            engine._load_model = slow_load

    service = fake_stt_service(HELLO, configure=hold_goodbye_while_loading)
    service.prepare(SttPrepareRequest(warm=False))
    switch = threading.Thread(target=service.apply_engine, args=(GOODBYE,))
    switch.start()
    assert loading.wait(5)

    during = service.transcribe(WAV, ZH).text
    release.set()
    switch.join(5)

    assert during == "你好"
    assert service.transcribe(WAV, ZH).text == "再見"


def test_the_fake_engine_is_not_offered_by_the_console():
    from nova_core.config.loader import dict_to_config
    from nova_core.server import runtime_settings

    assert [engine["id"] for engine in runtime_settings._stt_catalog()] == ["whisper"]
    with pytest.raises(runtime_settings.SettingsError, match="不支援的 STT 引擎"):
        runtime_settings.apply_stt_settings(
            dict_to_config({}), {"type": "fake", "model_size": "你好"},
            session_count=0, stt=fake_stt_service(HELLO))


def test_the_asr_section_of_the_config_selects_the_fake_engine():
    from nova_core.config.loader import dict_to_config

    asr = dict_to_config({"asr": {"type": "fake", "model_size": "歡迎光臨", "device": "cpu"}}).asr
    service = fake_stt_service(
        SttEngineSettings(engine=asr.type, model_size=asr.model_size, device=asr.device))

    assert service.transcribe(WAV, TranscriptionOptions(language="auto")).text == "歡迎光臨"
