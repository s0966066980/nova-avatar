# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Original-model acceleration stays optional and preserves fallback behavior."""
import asyncio
import queue
from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import torch
import pytest

from src.avatars.base import BaseAvatar

from src.config.schema import Config


def test_utilities_import_without_loading_optional_model_classes(monkeypatch):
    import builtins
    import importlib.util
    from pathlib import Path

    original_import = builtins.__import__

    def reject_model_import(name, *args, **kwargs):
        if name in {"models.vae", "models.unet"}:
            raise AssertionError("utility imports must not load model classes")
        return original_import(name, *args, **kwargs)

    path = Path(__file__).resolve().parents[1] / "src/avatars/musetalk/utils/utils.py"
    spec = importlib.util.spec_from_file_location(
        "src.avatars.musetalk.utils._import_probe", path
    )
    module = importlib.util.module_from_spec(spec)
    with monkeypatch.context() as isolated:
        isolated.setattr(builtins, "__import__", reject_model_import)
        spec.loader.exec_module(module)

    assert module.get_file_type("avatar.mp4") == "video"
    assert callable(module.load_all_model)


@pytest.mark.parametrize('batch_size,expected_shapes', [(1, [1]), (4, [4]), (8, [4, 8])])
def test_model_warmup_exercises_whisper_and_both_runtime_batch_shapes(batch_size, expected_shapes):
    from src.avatars.musetalk.avatar import warm_up

    calls = []

    class Features:
        def audio2feat(self, samples):
            calls.append(('whisper', len(samples)))
            return np.zeros((1500, 5, 384), np.float32)

        def feature2chunks(self, **kwargs):
            return [np.zeros((50, 384), np.float32)] * kwargs['batch_size']

    class UNet:
        dtype = torch.float32

        def __call__(self, latents, timesteps, **kwargs):
            calls.append(('unet', len(latents)))
            return SimpleNamespace(sample=latents)

    def decode(latents):
        calls.append(('vae', len(latents)))

    warm_up(batch_size, (SimpleNamespace(decode_latents=decode),
                SimpleNamespace(device=torch.device('cpu'), model=UNet()),
                lambda value: value, torch.tensor([0]), Features()))
    assert any(kind == 'whisper' for kind, _ in calls), 'first speech still pays Whisper cold start'
    assert [size for kind, size in calls if kind == 'unet'] == expected_shapes
    assert [size for kind, size in calls if kind == 'vae'] == expected_shapes


def test_engine_paths_survive_control_panel_save(monkeypatch, tmp_path):
    import src.config.overrides as overrides
    from src.config.loader import dict_to_config
    config = Config()
    config.model.musetalk.unet_engine_path = "/local/unet.engine"
    config.model.musetalk.vae_engine_path = "/local/vae.engine"
    monkeypatch.setattr(overrides, "RUNTIME_OVERRIDES_FILE", tmp_path / "runtime.yaml")
    overrides.persist_runtime_overrides(config)
    restored = dict_to_config(overrides.load_runtime_overrides())
    assert restored.model.musetalk.unet_engine_path == "/local/unet.engine"
    assert restored.model.musetalk.vae_engine_path == "/local/vae.engine"


def _builder_module():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "scripts/build-musetalk-tensorrt.py"
    spec = importlib.util.spec_from_file_location("musetalk_builder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_enabling_verified_engines_preserves_private_settings(monkeypatch, tmp_path):
    import hashlib
    import yaml
    import src.config.loader
    import src.config.overrides as overrides
    builder = _builder_module()
    path = tmp_path / "runtime.yaml"
    path.write_text("llm:\n  api_key: private-test-key\nmodel:\n  avatar_id: existing\n")
    engine = tmp_path / "unet.engine"
    engine.write_bytes(b"verified-test-engine")
    report = {"components": {"unet": {
        "engine": str(engine), "sha256": hashlib.sha256(engine.read_bytes()).hexdigest(),
        "batches": {"16": {"speedup": 2}},
    }}}
    monkeypatch.setattr(src.config.loader, "load_config", lambda _: Config())
    monkeypatch.setattr(overrides, "RUNTIME_OVERRIDES_FILE", path)
    builder.enable_engines(report, "unused.yaml")
    saved = yaml.safe_load(path.read_text())
    assert saved["llm"]["api_key"] == "private-test-key"
    assert saved["model"]["avatar_id"] == "existing"
    assert saved["model"]["musetalk"]["unet_engine_path"] == str(engine)
    backup, = tmp_path.glob("runtime_overrides-*.yaml.bak")
    assert "private-test-key" in backup.read_text()
    assert backup.stat().st_mode & 0o777 == 0o600
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("speedup,digest", [(0.9, "unused"), (2, "wrong-hash")])
def test_unverified_speed_or_changed_engine_never_enables(monkeypatch, tmp_path, speedup, digest):
    import src.config.loader
    import src.config.overrides as overrides
    path = tmp_path / "runtime.yaml"
    path.write_text("model: {}\n")
    engine = tmp_path / "unet.engine"
    engine.write_bytes(b"changed")
    report = {"components": {"unet": {
        "engine": str(engine), "sha256": digest,
        "batches": {"16": {"speedup": speedup}},
    }}}
    monkeypatch.setattr(src.config.loader, "load_config", lambda _: Config())
    monkeypatch.setattr(overrides, "RUNTIME_OVERRIDES_FILE", path)
    with pytest.raises(RuntimeError):
        _builder_module().enable_engines(report, "unused.yaml")
    assert path.read_text() == "model: {}\n"


def test_accelerated_vae_falls_back_for_unsupported_inputs():
    from src.avatars.musetalk.vae_acceleration import TensorRTVAEDecoder

    original_calls = []
    expected = np.zeros((1, 256, 256, 3), np.uint8)

    def decode(latents):
        original_calls.append(latents)
        return expected

    # Unsupported CPU input must be recoverable even without a GPU engine.
    decoder = TensorRTVAEDecoder.__new__(TensorRTVAEDecoder)
    decoder.original = SimpleNamespace(decode_latents=decode, scaling_factor=0.18215)
    decoder._lock, decoder._failed, decoder._stream = Lock(), False, None
    latents = torch.zeros((1, 4, 32, 32))
    assert decoder.decode_latents(latents) is expected
    assert decoder.decode_latents(latents) is expected
    assert len(original_calls) == 2
    assert decoder.scaling_factor == 0.18215


def test_unet_engine_unsupported_conditioning_preserves_original_fallback():
    from src.avatars.musetalk.inference_optimization import TensorRTUNet

    calls = []
    class Original(torch.nn.Module):
        dtype = torch.float32
        def forward(self, sample, timestep, **kwargs):
            calls.append((timestep, kwargs))
            return SimpleNamespace(sample=sample + timestep)
    engine = TensorRTUNet.__new__(TensorRTUNet)
    torch.nn.Module.__init__(engine)
    engine.original = Original()
    engine._lock, engine._failed, engine._stream = Lock(), False, None
    sample = torch.zeros(1, 8, 32, 32)
    features = torch.zeros(1, 50, 384)
    assert torch.all(engine(sample, 1, features).sample == 1)
    assert engine._failed
    assert torch.all(engine(sample, 2, features).sample == 2)
    assert [step for step, _ in calls] == [1, 2]
    assert calls[0][1]['encoder_hidden_states'] is features



def test_engine_paths_reach_the_production_loader(monkeypatch):
    from src.avatars.factory import prepare_avatar_model
    import src.avatars.musetalk.avatar as module
    config = Config()
    config.model.type = "musetalk"
    config.model.musetalk.unet_engine_path = "local/unet.engine"
    config.model.musetalk.vae_engine_path = "local/vae.engine"
    loaded = object()
    loader = Mock(return_value=loaded)
    monkeypatch.setattr(module, "load_model", loader)
    monkeypatch.setattr(module, "load_avatar", lambda _: "avatar")
    warmup = Mock()
    monkeypatch.setattr(module, "warm_up", warmup)
    assert prepare_avatar_model(config) == (loaded, "avatar")
    loader.assert_called_once_with(unet_engine_path="local/unet.engine", vae_engine_path="local/vae.engine")
    warmup.assert_called_once_with(config.model.batch_size, loaded)


def test_unavailable_engines_keep_the_original_models(monkeypatch):
    import src.avatars.musetalk.avatar as module
    vae = SimpleNamespace(vae=torch.nn.Identity())
    unet = SimpleNamespace(model=torch.nn.Identity())
    monkeypatch.setattr(module.torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(module, "load_all_model", lambda: (vae, unet, torch.nn.Identity()))
    monkeypatch.setattr(module, "Audio2Feature", lambda **_: "features")
    loaded = module.load_model(vae_engine_path="missing/vae.engine", unet_engine_path="missing/unet.engine")
    assert loaded[0] is vae
    assert loaded[1] is unet
    assert loaded[-1] == "features"


@pytest.mark.parametrize(
    "max_height,expected",
    [(960, (540, 960)), (0, (1080, 1920)), (2160, (1080, 1920))],
)
def test_renderer_limits_output_height_without_stretching_or_upscaling(
    max_height, expected
):
    async def run():
        quit_event = Event()
        avatar = BaseAvatar.__new__(BaseAvatar)
        avatar.config = SimpleNamespace(sessionid=7, video=SimpleNamespace(max_height=max_height))
        avatar.res_frame_queue = queue.Queue()
        avatar.frame_list_cycle = [np.zeros((1920, 1080, 3), dtype=np.uint8)]
        avatar.custom_index = {}
        avatar.custom_img_cycle = {}
        avatar.record_video_data = lambda _frame: None
        avatar.record_audio_data = lambda _frame: None
        avatar.res_frame_queue.put((None, 0, [(np.zeros(320, np.float32), 1, None)] * 2))

        class Track:
            def __init__(self, kind):
                self.kind, self.items = kind, []

            async def enqueue(self, frame, eventpoint=None):
                self.items.append(frame)
                if self.kind == "video":
                    quit_event.set()
                return True

        audio, video = Track("audio"), Track("video")
        await asyncio.wait_for(
            asyncio.to_thread(
                avatar.process_frames, quit_event,
                asyncio.get_running_loop(), audio, video,
            ),
            2,
        )
        assert (video.items[0].width, video.items[0].height) == expected
        assert [frame.samples for frame in audio.items] == [320, 320]

    asyncio.run(run())
