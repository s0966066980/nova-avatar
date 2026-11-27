# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The TTS layer's contract: its DTOs and the in-process adapter behind TtsService."""
from __future__ import annotations

import threading

import numpy as np
import pytest
from pydantic import ValidationError

from nova_contracts import CONTRACT_VERSION
from nova_contracts.tts import (
    FragmentEnvelope,
    PlayableFragment,
    SynthesisRequest,
    TtsEngineSettings,
    TtsError,
    TtsService,
    TtsVoice,
    strip_visual_markup,
)

SETTINGS = TtsEngineSettings(frames_per_second=50, matcha_threads=2)


class FakeEngine:
    """A TTS engine that turns each character into one 20 ms frame of 0.5."""

    def __init__(self, config, sink):
        self.config = config
        self.sink = sink
        self.queued = []
        self.flushed = 0
        self.rendered = None

    def txt_to_audio(self, msg):
        text, eventpoint = msg
        if text == "fail":
            raise RuntimeError("no connection")
        for _ in text:
            self.sink.put_audio_frame(np.full(320, 0.5, dtype=np.float32), eventpoint)

    def put_msg_txt(self, text, eventpoint=None):
        self.queued.append((text, eventpoint))

    def flush_talk(self):
        self.flushed += 1

    def has_pending_work(self):
        return bool(self.queued)

    def render(self, quit_event):
        self.rendered = quit_event


def service(**kwargs):
    from src.tts.adapter import InProcessTtsService

    created = []

    def create_engine(engine, config, sink):
        created.append(FakeEngine(config, sink))
        created[-1].engine_type = engine
        return created[-1]

    return InProcessTtsService(SETTINGS, create_engine=create_engine, **kwargs), created


def fragment(text="你好。"):
    return PlayableFragment(envelope=FragmentEnvelope(turn_id="t", generation=0, sequence=0),
                            text=text, estimated_seconds=0.5)


def test_a_voice_names_a_known_engine_and_nothing_else():
    assert TtsVoice(engine="matcha", voice="my-voice").server == ""
    with pytest.raises(ValidationError):
        TtsVoice(engine="cosyvoice")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        TtsVoice(engine="edgetts", ref_path="/etc/passwd")  # type: ignore[call-arg]


def test_engine_settings_refuse_impossible_values():
    with pytest.raises(ValidationError):
        TtsEngineSettings(matcha_threads=0)
    with pytest.raises(ValidationError):
        TtsEngineSettings(training_min_free_vram_gb=0)


def test_visual_markup_is_not_spoken():
    assert strip_visual_markup("**你好** 😀\n[官網](https://x.example)") == "你好，官網"
    assert strip_visual_markup("😀") == ""


def test_the_in_process_service_is_a_tts_service_reporting_the_contract_version():
    tts, _ = service()

    assert isinstance(tts, TtsService)
    health = tts.health()
    assert (health.contract_version, health.ready) == (CONTRACT_VERSION, True)


def test_synthesize_returns_the_fragment_as_16_bit_pcm():
    tts, created = service()

    pcm = b"".join(tts.synthesize(SynthesisRequest(fragment=fragment("你好"), voice=TtsVoice(engine="edgetts",
                                                                                              voice="zh-TW-HsiaoYuNeural"))))

    samples = np.frombuffer(pcm, dtype="<i2")
    assert samples.size == 2 * 320
    assert samples[0] == round(0.5 * 32767)
    engine = created[0]
    assert (engine.engine_type, engine.config.tts.ref_file, engine.config.audio.fps) == (
        "edgetts", "zh-TW-HsiaoYuNeural", 50)


def test_synthesize_stops_returning_audio_after_max_seconds():
    tts, _ = service()

    request = SynthesisRequest(fragment=fragment("一二三四五六"), voice=TtsVoice(engine="edgetts"),
                               max_seconds=0.04)
    pcm = b"".join(tts.synthesize(request))

    assert len(pcm) == 2 * 640


def test_a_failed_synthesis_is_a_tts_error():
    tts, _ = service()

    with pytest.raises(TtsError) as raised:
        b"".join(tts.synthesize(SynthesisRequest(fragment=fragment("fail"), voice=TtsVoice(engine="edgetts"))))
    assert "no connection" in raised.value.message


def test_a_speech_channel_feeds_the_sink_through_the_engine_and_switches_voice():
    tts, created = service()
    sink = object()
    voice = TtsVoice(engine="matcha", voice="model-a")

    channel = tts.open_channel(voice, sink)
    engine = created[0]
    channel.speak("你好", {"turn_id": "t"})
    quit_event = threading.Event()
    channel.run(quit_event)
    channel.flush()

    assert engine.sink is sink
    assert engine.queued == [("你好", {"turn_id": "t"})]
    assert channel.has_pending_work()
    assert engine.rendered is quit_event
    assert engine.flushed == 1
    assert (channel.voice, engine.config.matcha.num_threads) == (voice, 2)

    channel.set_voice(TtsVoice(engine="matcha", voice="model-b"))

    assert engine.config.tts.ref_file == "model-b"
    assert channel.voice.voice == "model-b"


def test_the_tts_openapi_posts_one_fragment_and_streams_pcm_back():
    from nova_contracts.http import openapi_document
    from nova_contracts.tts import HTTP_API

    document = openapi_document(HTTP_API)
    synthesize = document["paths"]["/synthesize"]["post"]

    assert synthesize["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SynthesisRequest"}
    assert list(synthesize["responses"]["200"]["content"]) == ["audio/L16;rate=16000"]
    assert document["components"]["schemas"]["TtsVoice"]["properties"]["engine"]["enum"] == [
        "edgetts", "breezyvoice", "matcha", "fake"]


def wav_bytes(seconds=1.0, rate=16000):
    import io

    import soundfile as sf

    buffer = io.BytesIO()
    sf.write(buffer, np.full(int(seconds * rate), 0.1, dtype=np.float32), rate, format="WAV")
    return buffer.getvalue()


@pytest.fixture
def library(tmp_path, monkeypatch):
    from src.tts import voice_library

    monkeypatch.setattr(voice_library, "VOICES_ROOT", tmp_path / "voices")
    return tmp_path / "voices"


def test_the_voice_library_round_trips_through_the_service(library):
    from nova_contracts.tts import VoiceRef, VoiceUpload

    tts, _ = service()

    voice = tts.add_voice(wav_bytes(), VoiceUpload(name="接待員", transcript="您好。"))

    assert (voice.name, voice.transcript, voice.seconds) == ("接待員", "您好。", 1.0)
    assert tts.list_voices().voices == (voice,)
    assert tts.catalog().voices == (voice,)
    assert tts.voice_audio(VoiceRef(voice_id=voice.id))[:4] == b"RIFF"
    assert not [path for path in library.iterdir() if path.name.startswith(".upload-")]
    tts.delete_voice(VoiceRef(voice_id=voice.id))
    assert tts.list_voices().voices == ()
    with pytest.raises(TtsError) as missing:
        tts.voice_audio(VoiceRef(voice_id=voice.id))
    assert missing.value.status == 404


def test_the_voice_library_refuses_oversized_or_undecodable_audio(library, monkeypatch):
    from nova_contracts.tts import VoiceUpload

    tts, _ = service()
    monkeypatch.setattr("src.tts.adapter.MAX_VOICE_UPLOAD_BYTES", 16)

    with pytest.raises(TtsError) as oversized:
        tts.add_voice(wav_bytes(), VoiceUpload())
    assert oversized.value.status == 413
    monkeypatch.setattr("src.tts.adapter.MAX_VOICE_UPLOAD_BYTES", 1024 * 1024)
    with pytest.raises(TtsError) as undecodable:
        tts.add_voice(b"not audio at all", VoiceUpload())
    assert undecodable.value.status == 400


def test_preparing_a_breezyvoice_voice_starts_its_server_and_returns_its_address(monkeypatch):
    from nova_contracts.tts import VoicePreparation
    from src.tts import cosyvoice_runtime

    started = []

    def ensure_server(**kwargs):
        started.append(kwargs)
        return "http://127.0.0.1:50001"

    monkeypatch.setattr(cosyvoice_runtime, "ensure_server", ensure_server)
    tts, _ = service()
    voice = TtsVoice(engine="breezyvoice", voice="0123456789abcdef", server="http://127.0.0.1:50001")

    prepared = tts.prepare_voice(VoicePreparation(voice=voice))

    assert prepared == voice.model_copy(update={"server": "http://127.0.0.1:50001"})
    assert started == [{"model_dir": "", "host": "127.0.0.1", "port": 50001}]


@pytest.mark.parametrize("error, status", [(FileNotFoundError("沒有權重"), 400), (TimeoutError("逾時"), 503)])
def test_a_breezyvoice_server_that_cannot_start_is_a_tts_error(monkeypatch, error, status):
    from nova_contracts.tts import VoicePreparation
    from src.tts import cosyvoice_runtime

    def ensure_server(**_kwargs):
        raise error

    monkeypatch.setattr(cosyvoice_runtime, "ensure_server", ensure_server)
    tts, _ = service()

    with pytest.raises(TtsError) as raised:
        tts.prepare_voice(VoicePreparation(voice=TtsVoice(engine="breezyvoice")))
    assert (raised.value.message, raised.value.status) == (str(error), status)


def test_preparing_an_edge_voice_warms_it_and_fails_when_edge_is_unreachable(monkeypatch):
    from nova_contracts.tts import VoicePreparation

    calls = []
    ready = [True, False]
    monkeypatch.setattr("src.tts.engines.edge.prewarm_edge_tts",
                        lambda voice, **kwargs: calls.append((voice, kwargs)) or ready.pop(0))
    tts, _ = service()
    voice = TtsVoice(engine="edgetts", voice="zh-TW-HsiaoYuNeural", edge_connection_reuse=False)

    assert tts.prepare_voice(VoicePreparation(voice=voice, timeout_seconds=5)) == voice
    with pytest.raises(TtsError):
        tts.prepare_voice(VoicePreparation(voice=voice))
    assert calls[0] == ("zh-TW-HsiaoYuNeural",
                        {"decode_pcm": True, "keep_connection": False, "timeout_seconds": 5})
    assert calls[1][1]["timeout_seconds"] == 15.0


def test_a_matcha_voice_needs_no_preparation():
    from nova_contracts.tts import VoicePreparation

    tts, _ = service()
    voice = TtsVoice(engine="matcha", voice="model-a")

    assert tts.prepare_voice(VoicePreparation(voice=voice)) == voice


def test_server_status_reports_the_normalized_address(monkeypatch):
    from src.tts import cosyvoice_runtime

    monkeypatch.setattr(cosyvoice_runtime, "server_ready", lambda server, model: (server, model) == ("", "m"))
    tts, _ = service()

    status = tts.server_status(TtsVoice(engine="breezyvoice", model="m"))

    assert (status.ready, status.url) == (True, "http://127.0.0.1:50000")


def test_a_voice_model_preview_uses_the_shared_thread_count_and_its_own_deadline(monkeypatch):
    from nova_contracts.tts import VoiceModelPreview
    from src.tts.voice_preview import PreviewError

    calls = []

    def synthesize_preview(voice_id, sentence, *, num_threads, keep_going):
        calls.append((voice_id, sentence, num_threads, keep_going()))
        if voice_id == "missing":
            raise PreviewError("找不到聲線模型", status=404)
        return b"RIFF"

    monkeypatch.setattr("src.tts.adapter.synthesize_preview", synthesize_preview)
    tts, _ = service()

    assert tts.preview_voice_model(VoiceModelPreview(voice_id="model-a", sentence="digits")) == b"RIFF"
    with pytest.raises(TtsError) as missing:
        tts.preview_voice_model(VoiceModelPreview(voice_id="missing", sentence="zh"))
    assert calls[0] == ("model-a", "digits", 2, True)
    assert (missing.value.message, missing.value.status) == ("找不到聲線模型", 404)
    with pytest.raises(ValidationError):
        VoiceModelPreview(voice_id="model-a", sentence="說任何話")  # type: ignore[arg-type]


def test_closing_stops_jobs_edge_and_owned_servers_and_a_forced_close_only_the_servers(monkeypatch):
    from src.tts import cosyvoice_runtime

    stopped = []
    monkeypatch.setattr(cosyvoice_runtime, "shutdown_cosyvoice_server", lambda: stopped.append("breezyvoice"))
    monkeypatch.setattr("src.tts.engines.edge.shutdown_edge_tts", lambda: stopped.append("edge"))
    tts, _ = service()
    monkeypatch.setattr(tts, "_stop_training", lambda: stopped.append("training"))

    tts.close(force=True)
    assert stopped == ["breezyvoice"]
    stopped.clear()
    tts.close()
    assert stopped == ["training", "edge", "breezyvoice"]


# ---- voice training
# Corpora, transcription and training jobs: the DTOs, and the layer's in-process
# implementation (InProcessVoiceTraining) seen through the VoiceTraining protocol.


def _training(tmp_path, **kwargs):
    from nova_contracts.tts import VoiceTraining
    from src.tts.training.corpus import CorpusStore
    from src.tts.training.service import InProcessVoiceTraining

    training = InProcessVoiceTraining(settings=TtsEngineSettings, corpus_store=CorpusStore(tmp_path), **kwargs)
    assert isinstance(training, VoiceTraining)
    return training


def test_transcript_files_travel_as_base64_and_come_back_as_the_same_bytes():
    from nova_contracts.tts import TranscriptFile, TranscriptImport

    raw = "﻿第一句\n".encode("utf-8") + b"\xff"
    request = TranscriptImport(slug="mine", files=(TranscriptFile(name="take.txt", content=raw),))

    assert TranscriptImport.model_validate_json(request.model_dump_json()).files[0].content == raw


@pytest.mark.parametrize("review", ["approved", "", "CONFIRMED"])
def test_a_line_edit_names_only_a_known_review_state(review):
    from nova_contracts.tts import LineEdit

    with pytest.raises(ValidationError):
        LineEdit(slug="mine", line_id="000001", review=review)


def test_a_training_check_status_is_pass_fail_or_warn():
    from nova_contracts.tts import TrainingCheck

    assert TrainingCheck(id="corpus_size", label="語料份量", status="warn", reason="少").status == "warn"
    with pytest.raises(ValidationError):
        TrainingCheck(id="x", label="x", status="ok", reason="x")


def test_a_corpus_is_created_listed_and_refused_through_the_protocol(tmp_path):
    from nova_contracts.tts import CorpusCreation, CorpusRef

    training = _training(tmp_path)
    created = training.create_corpus(CorpusCreation(slug="mine", source="self-recorded", consent=True))

    assert (created.slug, created.usage_label, created.counts.total) == ("mine", "Research / Non-commercial", 0)
    assert [item.slug for item in training.list_corpora().corpora] == ["mine"]
    with pytest.raises(TtsError) as missing:
        training.get_corpus(CorpusRef(slug="nobody"))
    assert missing.value.status == 404 and missing.value.message
    with pytest.raises(TtsError) as no_consent:
        training.create_corpus(CorpusCreation(slug="other", source="self-recorded"))
    assert no_consent.value.status == 400


def test_transcript_problems_come_back_as_extra_problems(tmp_path):
    from nova_contracts.tts import CorpusCreation, TranscriptFile, TranscriptImport

    training = _training(tmp_path)
    training.create_corpus(CorpusCreation(slug="mine", source="self-recorded", consent=True))

    with pytest.raises(TtsError) as refused:
        training.import_transcripts(TranscriptImport(
            slug="mine", files=(TranscriptFile(name="notes.doc", content=b"x"),)))

    assert refused.value.extra["problems"] and "notes.doc" in refused.value.extra["problems"][0]


def test_the_layers_preflight_has_no_stage_or_admin_check(tmp_path):
    from nova_contracts.tts import TrainingQuery
    from src.tts.training.gpu_probe import VramReading

    training = _training(tmp_path, vram_probe=lambda: VramReading(None, "no GPU"))
    status = training.training_status(TrainingQuery())
    ids = [check.id for check in status.preflight.checks]

    assert "stage_connections" not in ids and "admin" not in ids
    assert ids[0] == "free_vram" and not status.preflight.can_start
    assert status.job is None and status.settings.edge_clause.text


def test_a_core_cpu_reason_keeps_a_transcription_off_the_gpu(tmp_path):
    from nova_contracts.tts import CorpusCreation, TranscriptionStart
    from src.tts.training.corpus import CorpusStore
    from src.tts.training.gpu_guard import DeviceChoice
    from src.tts.training.service import InProcessVoiceTraining
    from src.tts.training.transcription import TranscriptionJobs
    from tests.training_fakes import tone_wav

    class Transcriber:
        def transcribe(self, path):
            return "文字"

        def close(self):
            pass

    store = CorpusStore(tmp_path)
    jobs = TranscriptionJobs(store, lambda model, device: Transcriber(), lambda: DeviceChoice("cuda"))
    training = InProcessVoiceTraining(settings=TtsEngineSettings, corpus_store=store, transcription=jobs)
    training.create_corpus(CorpusCreation(slug="mine", source="self-recorded", consent=True))
    store.add_line("mine", tone_wav(), ".wav")

    started = training.start_transcription(TranscriptionStart(slug="mine", model="small", cpu_reason="有舞台連線"))
    assert jobs.wait(10)

    assert (started.device, started.fallback_reason) == ("cpu", "有舞台連線")


def test_a_running_job_is_reported_as_training_activity(tmp_path):
    from nova_contracts.tts import TrainingStart
    from tests.training_fakes import rig

    r = rig(tmp_path, train_code=None)
    training = _training(tmp_path / "unused", training_jobs=r.manager)
    assert training.training_activity().active is False

    job = training.start_training(TrainingStart(corpus="voice", name="我的聲音"))
    try:
        assert job.status == "running" and training.training_activity().active is True
    finally:
        assert training.cancel_training().job is not None
        r.manager.join(20)
    assert training.training_activity().active is False
