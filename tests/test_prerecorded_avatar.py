# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
from fractions import Fraction
from unittest.mock import patch

import av
import numpy as np
import pytest

from src.avatars import presentation
from src.avatars.factory import prepare_avatar_model
from src.avatars.prerecorded import clock_image
from src.config.schema import Config


@pytest.fixture
def character(tmp_path, monkeypatch):
    from src.config import overrides
    monkeypatch.setattr(overrides, "RUNTIME_OVERRIDES_FILE", tmp_path / "runtime_overrides.yaml")
    monkeypatch.setattr(presentation, "avatars_root", lambda: tmp_path)
    (tmp_path / "example").mkdir()
    config = Config()
    config.model.avatar_id = "example"
    return config


def clip(path, *, size=(64, 96), count=48, fps=24):
    with av.open(str(path), "w") as container:
        video = container.add_stream("libx264", rate=fps)
        video.width, video.height, video.pix_fmt = *size, "yuv420p"
        video.options = {"preset": "ultrafast", "crf": "18"}
        for index in range(count):
            image = np.full((size[1], size[0], 3), (40, 190, 60), dtype=np.uint8)
            image[20:70, 20:45] = (100 + index % 30, 80, 60)
            frame = av.VideoFrame.from_ndarray(image, format="bgr24")
            frame.pts, frame.time_base = index, Fraction(1, fps)
            for packet in video.encode(frame):
                container.mux(packet)
        for packet in video.encode():
            container.mux(packet)


def publish(config, slot, *, size=(64, 96)):
    import uuid
    source = presentation.folder(config.model.avatar_id) / f"{uuid.uuid4().hex}.mp4"
    clip(source, size=size)
    result = {"name": source.name, "width": size[0], "height": size[1], "fps": 25,
              "url": f"/api/presentation/example/media/{source.name}", "duration": 2.0}
    presentation.candidate(config.model.avatar_id, slot, result)
    return result


def test_candidates_are_not_active_and_missing_pair_blocks_boot(character):
    character.model.presentation_modes["example"] = "prerecorded"
    publish(character, "idle")
    with pytest.raises(presentation.PresentationError, match="缺少"):
        prepare_avatar_model(character)
    presentation.apply_asset("example", "idle")
    publish(character, "talking")
    assert not presentation.snapshot(character)["ready"]
    presentation.apply_asset("example", "talking")
    with patch.dict("sys.modules", {"src.avatars.musetalk.avatar": None}):
        model, assets = prepare_avatar_model(character)
    assert model is None
    assert assets["ready"]


def test_prerecorded_resolution_is_independent_of_musetalk_output(character):
    character.video.max_height = 54
    character.model.presentation_modes["example"] = "prerecorded"
    for slot in presentation.SLOTS:
        publish(character, slot)
        presentation.apply_asset("example", slot)
    value = presentation.snapshot(character)
    assert value["max_height"] == 0
    assert value["slots"]["idle"]["current"]["height"] == 96
    assert character.video.max_height == 54


def test_mode_switch_keeps_event_loop_responsive_and_same_mode_skips_reload(character):
    import asyncio
    import time
    from unittest.mock import AsyncMock
    from src.server.state import state
    from src.server.routes.presentation import set_presentation
    for slot in presentation.SLOTS:
        publish(character, slot)
        presentation.apply_asset("example", slot)
    request = AsyncMock()
    request.match_info = {"avatar_id": "example"}
    request.json.return_value = {"mode": "prerecorded"}
    def slow_reload(*args):
        time.sleep(.15)
    async def run():
        pulses = []
        async def pulse():
            await asyncio.sleep(.02)
            pulses.append(time.monotonic())
        start = time.monotonic()
        with patch("src.server.runtime_settings._reload_avatar", side_effect=slow_reload) as reload:
            result, _ = await asyncio.gather(set_presentation(request), pulse())
            assert result.status == 200
            assert pulses[0] - start < .1, "model reload blocked HTTP event loop"
            assert (await set_presentation(request)).status == 200
            assert reload.call_count == 1, "selecting the current mode reloaded the model"
    with (patch.object(state, "config", character), patch.object(state, "avatar_streams", {}),
          patch.object(state, "pcs", set()), patch.object(state, "switching", False),
          patch("src.config.overrides.persist_runtime_overrides")):
        asyncio.run(run())


def test_mismatched_size_and_failure_preserve_current_pair(character):
    first = publish(character, "idle")
    presentation.apply_asset("example", "idle")
    publish(character, "talking", size=(80, 96))
    with pytest.raises(presentation.PresentationError, match="相同尺寸"):
        presentation.apply_asset("example", "talking")
    assert presentation.read("example")["idle"]["current"] == first


def test_apply_and_restore_do_not_modify_original_role(character):
    original = presentation.folder("example").parent / "source.mp4"
    original.write_bytes(b"original")
    first = publish(character, "talking")
    presentation.apply_asset("example", "talking")
    second = publish(character, "talking")
    presentation.apply_asset("example", "talking")
    assert presentation.read("example")["talking"]["current"] == second
    presentation.apply_asset("example", "talking", restore=True)
    assert presentation.read("example")["talking"]["current"] == first
    assert original.read_bytes() == b"original"


def test_normalize_preserves_time_resamples_and_outputs_no_audio(tmp_path):
    source, destination = tmp_path / "source.mp4", tmp_path / "target.mp4"
    clip(source)
    metadata = presentation.normalize(source, destination)
    assert metadata["frames"] == 50
    assert metadata["duration"] == 2.0
    with av.open(str(destination)) as movie:
        assert not movie.streams.audio
        assert movie.streams.video[0].average_rate == 25
        frames = list(movie.decode(video=0))
        assert len(frames) == 50
        assert frames[-1].time == pytest.approx(1.96)


def test_cancel_normalization_does_not_publish(character, tmp_path):
    source, destination = tmp_path / "source.mp4", tmp_path / "target.mp4"
    clip(source)
    with pytest.raises(InterruptedError):
        presentation.normalize(source, destination, cancelled=lambda: True)
    assert presentation.read("example") == {"idle": {}, "talking": {}}


def test_untrusted_paths_cannot_escape_asset_folder(character):
    for value in ("../outside", "example/../../outside"):
        with pytest.raises(presentation.PresentationError):
            presentation.folder(value)
    with pytest.raises(presentation.PresentationError):
        presentation.media_path("example", "../source.mp4")


def test_clock_signature_and_time_survive_actual_h264(tmp_path):
    path = tmp_path / "clock.mp4"
    milliseconds = [0, 12345, 620004]
    with av.open(str(path), "w") as output:
        stream = output.add_stream("libx264", rate=25)
        stream.width, stream.height, stream.pix_fmt = 64, 32, "yuv420p"
        for index, tick in enumerate(milliseconds):
            frame = av.VideoFrame.from_ndarray(clock_image(tick), format="bgr24")
            frame.pts = index
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)
    decoded = []
    with av.open(str(path)) as incoming:
        for frame in incoming.decode(video=0):
            pixels = frame.to_ndarray(format="rgb24")
            word = 0
            for bit in range(32):
                y, x = divmod(bit, 8)
                word = (word << 1) | int(pixels[y * 8 + 4, x * 8 + 4, 0] > 127)
            assert word >> 24 == 0xA5
            decoded.append(word & 0xFFFFFF)
    assert decoded == milliseconds


def test_transport_clock_is_stamped_at_actual_video_release():
    import asyncio
    from types import SimpleNamespace
    from src.utils.webrtc import PlayerStreamTrack
    async def scenario():
        player = SimpleNamespace(clock_only=True, _start=lambda track: None,
                                 _stop=lambda track: None, notify_media_timing=lambda *args: None)
        track = PlayerStreamTrack(player, kind="video")
        initial = av.VideoFrame.from_ndarray(np.zeros((32, 64, 3), np.uint8), format="bgr24")
        await track._queue.put((initial, None))
        frame = await asyncio.wait_for(track.recv(), timeout=1)
        assert frame.width == 64 and frame.height == 32
        assert np.array_equal(frame.to_ndarray(format="bgr24"), clock_image(round(frame.pts / 90000 * 1000)))
        track.stop()
    asyncio.run(scenario())


def test_failed_persistence_keeps_loaded_avatar_and_settings(monkeypatch):
    from src.server.state import state
    from src.server.runtime_settings import _reload_avatar, SettingsError
    from src.scene.service import scene_service
    config = Config()
    original_id = config.model.avatar_id
    old_model, old_avatar = object(), object()
    monkeypatch.setattr(state, "model", old_model)
    monkeypatch.setattr(state, "avatar", old_avatar)
    monkeypatch.setattr(state, "model_ready", True)
    monkeypatch.setattr(state, "switching", False)
    with patch("src.avatars.factory.prepare_avatar_model", return_value=(object(), object())), patch(
        "src.avatars.factory.load_avatar_data", return_value=object()
    ), patch(
        "src.server.runtime_settings.persist_runtime_overrides", side_effect=OSError("disk full")
    ), patch.object(scene_service, "select") as select:
        with pytest.raises(SettingsError, match="disk full"):
            _reload_avatar(config, "musetalk", "another")
    assert config.model.avatar_id == original_id
    assert state.model is old_model and state.avatar is old_avatar
    assert state.model_ready and not state.switching
    assert select.call_count == 2


def test_switch_to_another_prerecorded_role_unloads_mouth_weights(monkeypatch):
    from src.server.state import state
    from src.server.runtime_settings import _reload_avatar
    config = Config()
    config.model.presentation_modes["another"] = "prerecorded"
    monkeypatch.setattr(state, "model", object())
    monkeypatch.setattr(state, "avatar", object())
    monkeypatch.setattr(state, "model_ready", True)
    monkeypatch.setattr(state, "switching", False)
    with patch("src.avatars.factory.prepare_avatar_model", return_value=(None, {"ready": True})) as prepare, patch(
        "src.avatars.factory.load_avatar_data"
    ) as load, patch("src.scene.service.scene_service.select"), patch(
        "src.server.runtime_settings.persist_runtime_overrides"
    ), patch("src.server.runtime_settings._release_gpu_resources"):
        _reload_avatar(config, "musetalk", "another")
    prepare.assert_called_once()
    load.assert_not_called()
    assert state.model is None and state.model_ready


def test_presentation_mode_survives_runtime_override_reload(tmp_path, monkeypatch):
    from src.config import overrides
    config = Config()
    config.model.presentation_modes = {"one": "prerecorded", "two": "musetalk"}
    monkeypatch.setattr(overrides, "RUNTIME_OVERRIDES_FILE", tmp_path / "runtime.yaml")
    overrides.persist_runtime_overrides(config)
    assert overrides.load_runtime_overrides()["model"]["presentation_modes"] == config.model.presentation_modes


def test_job_initialization_failure_releases_exclusive_gpu_locks(character, monkeypatch):
    from src.server import presentation_jobs as jobs
    from src.server.import_jobs import _WORKER_LOCK
    from src.server.runtime_settings import _SWITCH_LOCK
    from src.server.state import state
    monkeypatch.setattr(state, "avatar_streams", {})
    monkeypatch.setattr(state, "pcs", set())
    monkeypatch.setattr(state, "switching", False)
    with patch.object(jobs, "_save", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            jobs.submit("generate", config=character, avatar_id="example", text="sample")
    assert not state.switching
    assert _SWITCH_LOCK.acquire(blocking=False)
    _SWITCH_LOCK.release()
    assert _WORKER_LOCK.acquire(blocking=False)
    _WORKER_LOCK.release()


@pytest.mark.parametrize("failure", [presentation.PresentationError("文字不足五秒"), InterruptedError("已取消")])
def test_production_failure_and_cancel_restore_mode_and_release_resources(character, monkeypatch, failure):
    from types import SimpleNamespace
    from src.server import presentation_jobs as jobs
    from src.server.import_jobs import _WORKER_LOCK
    from src.server.runtime_settings import _SWITCH_LOCK
    from src.server.state import state
    character.model.presentation_modes["example"] = "prerecorded"
    monkeypatch.setattr(state, "config", character)
    monkeypatch.setattr(state, "avatar_streams", {})
    monkeypatch.setattr(state, "pcs", set())
    monkeypatch.setattr(state, "model", None)
    monkeypatch.setattr(state, "avatar", {"ready": True})
    monkeypatch.setattr(state, "model_ready", True)
    monkeypatch.setattr(state, "switching", False)
    monkeypatch.setattr(jobs.threading, "Thread", lambda *, target, **kwargs: SimpleNamespace(start=target))
    with patch.object(jobs, "generate", side_effect=failure), patch.object(jobs, "_release") as release, patch(
        "src.avatars.factory.prepare_avatar_model", return_value=(None, {"ready": True})
    ):
        created = jobs.submit("generate", config=character, avatar_id="example", text="sample")
    value = jobs.status(created["id"])
    assert value["status"] == ("cancelled" if isinstance(failure, InterruptedError) else "failed")
    assert state.model_ready and state.avatar == {"ready": True} and not state.switching
    assert character.model.presentation_modes["example"] == "prerecorded"
    assert release.call_count == 2
    assert not list(presentation.folder("example").glob("*.mp4"))
    assert _SWITCH_LOCK.acquire(blocking=False)
    _SWITCH_LOCK.release()
    assert _WORKER_LOCK.acquire(blocking=False)
    _WORKER_LOCK.release()


def test_restart_marks_job_failed_and_cleans_unpublished_files(character):
    from src.server import presentation_jobs as jobs
    job_id = "b" * 32
    source = jobs.root() / ("a" * 32 + ".upload")
    destination = presentation.folder("example") / ("c" * 32 + ".mp4")
    source.write_bytes(b"input")
    destination.write_bytes(b"partial")
    jobs._save({"id": job_id, "status": "running", "avatar_id": "example",
                "temporary_source": source.name, "temporary_asset": destination.name})
    assert jobs.status(job_id)["status"] == "failed"
    assert not source.exists() and not destination.exists()
    assert presentation.read("example") == {"idle": {}, "talking": {}}


def test_restart_preserves_uploaded_recording_for_retry(character):
    from src.server import presentation_jobs as jobs
    job_id = "f" * 32
    source = jobs.root() / ("d" * 32 + ".upload")
    source.write_bytes(b"captured scene")
    jobs._save({"id": job_id, "kind": "record", "status": "running",
                "temporary_source": source.name, "source_suffix": ".mp4"})
    value = jobs.status(job_id)
    assert value["status"] == "failed"
    original = presentation.avatars_root().parent / "records" / value["original"]["filename"]
    assert original.read_bytes() == b"captured scene"
    assert not source.exists()


def test_failed_mode_and_asset_apply_restore_previous_pair(character, monkeypatch):
    import asyncio
    import json
    from types import SimpleNamespace
    from src.server.routes.presentation import set_presentation
    from src.server.state import state
    character.model.presentation_modes["example"] = "prerecorded"
    publish(character, "idle")
    presentation.apply_asset("example", "idle")
    first = publish(character, "talking")
    presentation.apply_asset("example", "talking")
    publish(character, "talking")
    before = presentation.read("example")
    monkeypatch.setattr(state, "config", character)
    monkeypatch.setattr(state, "avatar_streams", {})
    monkeypatch.setattr(state, "pcs", set())
    monkeypatch.setattr(state, "switching", False)
    async def params():
        return {"action": "apply", "slot": "talking"}
    request = SimpleNamespace(match_info={"avatar_id": "example"}, json=params)
    with patch("src.server.runtime_settings._reload_avatar", side_effect=OSError("reload failed")):
        response = asyncio.run(set_presentation(request))
    assert response.status == 500
    assert presentation.read("example") == before
    assert presentation.read("example")["talking"]["current"] == first
    assert "reload failed" in json.loads(response.text)["msg"]


def test_media_activity_uses_pcm_clock_and_emits_only_edges():
    import json
    from src.server.voice_session import VoiceTurnSession
    config = Config()
    config.model.presentation_modes[config.model.avatar_id] = "prerecorded"
    session = VoiceTurnSession.__new__(VoiceTurnSession)
    session.config = config
    session._turn_id, session._generation, session._sequence = "turn", 4, 0
    events = []
    session._event_sink = lambda raw: events.append(json.loads(raw))
    session.on_output_audio_clock(False, 1.0, None)
    session.on_output_audio_clock(True, 1.2, None)
    session.on_output_audio_clock(True, 1.4, None)
    session.on_output_audio_clock(False, 1.6, None)
    assert [(e["active"], e["media_ms"]) for e in events] == [(True, 1200), (False, 1600)]
    assert all(e["turn_id"] == "turn" and e["generation"] == 4 for e in events)


def test_failed_export_preserves_original_browser_recording(character, monkeypatch):
    from types import SimpleNamespace
    from src.server import presentation_jobs as jobs
    source = jobs.root() / ("e" * 32 + ".upload")
    source.write_bytes(b"browser recording")
    monkeypatch.setattr(jobs.threading, "Thread", lambda *, target, **kwargs: SimpleNamespace(start=target))
    with patch.object(jobs, "transcode_record", side_effect=ValueError("invalid codec")):
        created = jobs.submit("record", config=character, source=source, source_suffix=".webm")
    value = jobs.status(created["id"])
    assert value["status"] == "failed"
    assert not source.exists()
    original = presentation.avatars_root().parent / "records" / value["original"]["filename"]
    assert original.read_bytes() == b"browser recording"


def test_webm_export_keeps_video_timestamps_and_assistant_audio(tmp_path):
    from src.server.presentation_jobs import transcode_record
    source, destination = tmp_path / "capture.webm", tmp_path / "export.mp4"
    with av.open(str(source), "w") as output:
        video = output.add_stream("libvpx", rate=25)
        video.width, video.height, video.pix_fmt = 64, 96, "yuv420p"
        audio = output.add_stream("libopus", rate=48000)
        audio.layout = "mono"
        for index in range(100):
            pcm = (np.sin(2 * np.pi * 440 * (np.arange(960) + index * 960) / 48000) * 8000).astype(np.int16)
            frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="s16", layout="mono")
            frame.sample_rate, frame.pts, frame.time_base = 48000, index * 960, Fraction(1, 48000)
            for packet in audio.encode(frame):
                output.mux(packet)
            if index % 2 == 0:
                frame = av.VideoFrame.from_ndarray(np.full((96, 64, 3), 100, np.uint8), format="rgb24")
                frame.pts, frame.time_base = index // 2, Fraction(1, 25)
                for packet in video.encode(frame):
                    output.mux(packet)
        for stream in (video, audio):
            for packet in stream.encode():
                output.mux(packet)
    transcode_record(source, destination, lambda _: None, lambda: False)
    with av.open(str(destination)) as movie:
        assert movie.streams.video[0].codec_context.name == "h264"
        assert movie.streams.audio[0].codec_context.name == "aac"
        video_frames, audio_frames = [], []
        for frame in movie.decode():
            (video_frames if isinstance(frame, av.VideoFrame) else audio_frames).append(frame)
        assert len(video_frames) == 50
        assert video_frames[-1].time == pytest.approx(1.96, abs=0.01)
        assert sum(f.samples for f in audio_frames) / 48000 == pytest.approx(2.0, abs=0.03)
        assert np.max(np.abs(audio_frames[5].to_ndarray())) > 0.1

    # Browser-native H.264/AAC is exported without decoding/re-encoding.
    copied = tmp_path / "copied.mp4"
    transcode_record(destination, copied, lambda _: None, lambda: False)
    with av.open(str(copied)) as movie:
        frames = list(movie.decode(video=0))
        assert len(frames) == 50
        assert frames[-1].time == pytest.approx(1.96, abs=0.01)
    def bitstreams(path):
        with av.open(str(path)) as movie:
            return [bytes(packet) for packet in movie.demux() if packet.dts is not None]
    assert bitstreams(copied) == bitstreams(destination)


def test_h264_opus_export_only_converts_audio(tmp_path):
    from src.server.presentation_jobs import transcode_record
    source, destination = tmp_path / "capture.mp4", tmp_path / "export.mp4"
    with av.open(str(source), "w") as output:
        video = output.add_stream("libx264", rate=25)
        video.width, video.height, video.pix_fmt = 64, 96, "yuv420p"
        audio = output.add_stream("libopus", rate=48000)
        audio.layout = "mono"
        for index in range(100):
            pcm = (np.sin(2 * np.pi * 440 * (np.arange(960) + index * 960) / 48000) * 8000).astype(np.int16)
            frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="s16", layout="mono")
            frame.sample_rate, frame.pts, frame.time_base = 48000, index * 960, Fraction(1, 48000)
            for packet in audio.encode(frame):
                output.mux(packet)
            if index % 2 == 0:
                frame = av.VideoFrame.from_ndarray(np.full((96, 64, 3), 100, np.uint8), format="rgb24")
                frame.pts, frame.time_base = index // 2, Fraction(1, 25)
                for packet in video.encode(frame):
                    output.mux(packet)
        for stream in (video, audio):
            for packet in stream.encode():
                output.mux(packet)
    transcode_record(source, destination, lambda _: None, lambda: False)
    def video_packets(path):
        with av.open(str(path)) as movie:
            return [bytes(packet) for packet in movie.demux(video=0) if packet.dts is not None]
    assert video_packets(source) == video_packets(destination)
    with av.open(str(destination)) as movie:
        assert movie.streams.audio[0].codec_context.name == "aac"
        samples = list(movie.decode(audio=0))
        assert np.max(np.abs(samples[5].to_ndarray())) > 0.1


def test_trailing_silence_cannot_make_a_short_script_long_enough(character, tmp_path):
    from types import SimpleNamespace
    from src.server.presentation_jobs import generate
    def engine(kind, config, parent):
        return SimpleNamespace(txt_to_audio=lambda _: parent.put_audio_frame(
            np.concatenate([np.zeros(1600), np.full(64000, 0.1), np.zeros(32000)])
        ))
    with patch("src.tts.factory.create_tts_engine", side_effect=engine), patch(
        "src.avatars.musetalk.avatar.load_model"
    ) as load:
        with pytest.raises(presentation.PresentationError, match="不足五秒"):
            generate(character, "example", "short", tmp_path / "short.mp4", lambda _: None, lambda: False)
    load.assert_not_called()
