# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Console output settings persist and feed new avatar renderer sessions."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
import pytest

from src.config.loader import dict_to_config
from src.config.overrides import load_runtime_overrides, persist_runtime_overrides
from src.config.schema import Config
from src.server import runtime_settings


def test_output_resolution_survives_restart_and_other_settings_saves(tmp_path):
    config = Config()
    config.video.max_height = 960
    path = tmp_path / 'runtime_overrides.yaml'
    with patch('src.config.overrides.RUNTIME_OVERRIDES_FILE', path):
        persist_runtime_overrides(config)
        restored = dict_to_config(load_runtime_overrides())
        assert restored.video.max_height == 960
        restored.stage.caption_max_chars = 200
        persist_runtime_overrides(restored)
        assert dict_to_config(load_runtime_overrides()).video.max_height == 960


def test_snapshot_reports_actual_dimensions_without_stretching_or_upscaling(tmp_path):
    config = Config()
    config.model.avatar_id = 'portrait'
    preview = tmp_path / 'portrait' / 'full_imgs' / '00000000.png'
    preview.parent.mkdir(parents=True)
    Image.new('RGB', (1080, 1920)).save(preview)
    with patch('src.server.runtime_settings.avatars_root', return_value=tmp_path):
        for limit, expected in [(960, (540, 960)), (720, (404, 720)), (0, (1080, 1920)), (2160, (1080, 1920))]:
            config.video.max_height = limit
            snapshot = runtime_settings.video_output_snapshot(config)
            assert (snapshot['source_width'], snapshot['source_height']) == (1080, 1920)
            assert (snapshot['output_width'], snapshot['output_height']) == expected
            assert snapshot['max_height'] == limit


@pytest.mark.parametrize('invalid', [-1, 1, 2161, 720.5, True, '720', None])
def test_invalid_height_never_changes_or_persists_settings(invalid):
    config = Config()
    config.video.max_height = 1280
    with patch('src.server.runtime_settings.persist_runtime_overrides') as persist:
        with pytest.raises(runtime_settings.SettingsError):
            runtime_settings.apply_video_settings(config, {'max_height': invalid})
    assert config.video.max_height == 1280
    persist.assert_not_called()


def test_persist_failure_restores_previous_output_height():
    config = Config()
    config.video.max_height = 1280
    with patch('src.server.runtime_settings.persist_runtime_overrides', side_effect=OSError('disk full')):
        with pytest.raises(OSError):
            runtime_settings.apply_video_settings(config, {'max_height': 960})
    assert config.video.max_height == 1280


def test_new_avatar_session_uses_saved_height_and_existing_session_keeps_dimensions():
    from src.avatars.factory import create_avatar

    config = Config()
    config.model.type = 'musetalk'
    config.video.max_height = 1280
    existing = SimpleNamespace(config=deepcopy(config))
    with patch('src.server.runtime_settings.persist_runtime_overrides'), patch(
        'src.avatars.musetalk.avatar.MuseTalkAvatar',
        side_effect=lambda settings, *_: SimpleNamespace(config=settings),
    ):
        runtime_settings.apply_video_settings(config, {'max_height': 960})
        created = create_avatar(config, None, None, sessionid=123)
    assert created.config.video.max_height == 960
    assert existing.config.video.max_height == 1280
    assert created.config.sessionid == 123


@pytest.mark.parametrize('params', [None, [], {}, {'width': 720}])
def test_output_update_requires_an_object_and_explicit_height(params):
    with pytest.raises(runtime_settings.SettingsError):
        runtime_settings.apply_video_settings(Config(), params)


def test_fractional_reduction_filters_fine_detail_without_mutating_source():
    import numpy as np
    from src.avatars.video_output import limit_video_height

    checker = ((np.indices((1920, 1080)).sum(axis=0) % 2) * 255).astype(np.uint8)
    source = np.repeat(checker[:, :, None], 3, axis=2)
    original = source.copy()
    output = limit_video_height(source, 540)
    assert output.shape == (540, 304, 3)
    assert np.max(np.abs(output.astype(float) - 127.5)) <= 1
    assert np.array_equal(source, original)
    assert limit_video_height(source, 0) is source


def test_registered_output_route_saves_for_reconnect_and_rejects_invalid_input(tmp_path):
    import asyncio
    from aiohttp.test_utils import TestClient, TestServer
    from src.server.server import create_app
    from src.server.state import state

    async def run():
        config = Config()
        config.video.max_height = 1280
        path = tmp_path / 'runtime_overrides.yaml'
        with patch.object(state, 'config', config), patch.object(state, 'avatar_streams', {7: object()}), patch(
            'src.config.overrides.RUNTIME_OVERRIDES_FILE', path
        ):
            app = create_app()
            # This test owns no model processes, peers or scene workers.
            app.on_shutdown.clear()
            async with TestClient(TestServer(app)) as client:
                response = await client.post('/api/avatar/output', json={'max_height': 540})
                assert response.status == 200
                data = (await response.json())['data']
                assert data['max_height'] == 540
                assert data['requires_reconnect'] is True
                assert dict_to_config(load_runtime_overrides()).video.max_height == 540
                response = await client.post('/api/avatar/output', json={'max_height': -1})
                assert response.status == 400
                assert (await response.json())['code'] == -1
                assert config.video.max_height == 540

    asyncio.run(run())
