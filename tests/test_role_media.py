# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

import shutil
import subprocess
import asyncio
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest

from src.profiles.media import RolePresentation, TransitionMedia, WIDTH, HEIGHT
from src.profiles.store import ProfileError
from src.scene.service import scene_service


def test_role_continuity_masks_have_a_bounded_memory_cost():
    from src.avatars.musetalk.mouth_continuity import MouthContinuityController
    from src.avatars.musetalk.avatar_transition import AvatarTransitionController
    frame = np.zeros((1024, 1024, 3), np.uint8)
    mask = np.full((32, 32), 255, np.uint8)
    frames, masks = [frame] * 12, [mask] * 12
    coords = [(300, 300, 700, 700)] * 12
    mouth = MouthContinuityController(frames, masks, coords)
    transition = AvatarTransitionController(frames, masks, coords, coords, mouth_controller=mouth)
    def retained(collection):
        return (collection.retained_bytes if hasattr(collection, 'retained_bytes')
                else sum(mask.nbytes for mask in collection))
    for index in range(len(frames)):
        assert mouth._full_masks[index].shape == frame.shape[:2]
        assert transition._full_masks[index].shape == frame.shape[:2]
    total = retained(mouth._full_masks) + retained(transition._full_masks)
    assert total <= 40 * 1024 * 1024, f'role masks retained {total / 1024**2:.1f} MiB'


@pytest.mark.parametrize('effect', ['fade', 'slide_left', 'slide_right', 'zoom'])
def test_directed_effect_finishes_on_the_same_fixed_canvas(monkeypatch, effect):
    background = np.full((HEIGHT, WIDTH, 3), (100, 20, 10), np.uint8)
    monkeypatch.setattr(scene_service, "background_frame", lambda *_: background)
    old = np.full((128, 72, 3), (0, 255, 0), np.uint8)
    old[30:100, 20:50] = (20, 20, 220)
    new = old.copy()
    new[30:100, 20:50] = (220, 20, 20)
    tick = [0.]
    presentation = RolePresentation(clock=lambda: tick[0])
    presentation.compose(old, green_screen=True)
    presentation.begin("a-to-b", {"effect": effect, "duration": .6})
    first = presentation.compose(new, green_screen=True)
    assert first.shape == (HEIGHT, WIDTH, 3)
    assert np.array_equal(first[0, 0], background[0, 0])
    assert presentation.marker["role_transition_end"] is False
    tick[0] = .7
    last = presentation.compose(new, green_screen=True)
    assert presentation.marker == {"role_transition_id": "a-to-b", "role_transition_end": True}
    assert last[HEIGHT//2, WIDTH//2, 0] > first[HEIGHT//2, WIDTH//2, 0]
    presentation.close()
    assert presentation.marker == {}


def test_mid_clip_decoder_failure_falls_back_to_a_complete_fade(monkeypatch):
    monkeypatch.setattr(scene_service, 'background_frame', lambda *_: None)
    tick = [0.]
    presentation = RolePresentation(clock=lambda: tick[0])
    old = np.zeros((128, 72, 3), np.uint8)
    new = np.full_like(old, 200)
    presentation.compose(old, green_screen=False)
    closed = []
    reader = SimpleNamespace(failed=True, close=lambda: closed.append(True))
    presentation.begin('broken-video', {'kind':'video'}, reader=reader)
    tick[0] = 10
    presentation.compose(new, green_screen=False)
    assert closed == [True]
    assert not presentation.marker['role_transition_end']
    tick[0] = 10.7
    assert np.array_equal(presentation.compose(new, green_screen=False), np.full((HEIGHT, WIDTH, 3), 200, np.uint8))
    assert presentation.marker['role_transition_end']


def test_scheduled_video_holds_source_until_all_peers_are_ready(monkeypatch):
    monkeypatch.setattr(scene_service, 'background_frame', lambda *_: None)
    tick = [0.]
    source = np.full((128, 72, 3), (20, 20, 210), np.uint8)
    target = np.full_like(source, (20, 210, 20))
    clip = np.full_like(source, (230, 20, 20))
    requested = []
    reader = SimpleNamespace(frames=20, failed=False, last_index=0,
        close=lambda: None, frame=lambda index: requested.append(index) or clip)
    presentation = RolePresentation(clock=lambda: tick[0])
    original = presentation.compose(source, green_screen=False)
    presentation.begin('two-peer-video', {'kind': 'video'}, reader=reader, started_at=10.)

    tick[0] = 5.
    waiting = presentation.compose(target, green_screen=False)
    assert np.array_equal(waiting, original), 'preparing another peer exposed the clip or target'
    assert requested == [], 'the video must not be read before the common start time'
    assert presentation.marker == {}, 'preparation must not emit transition media markers'

    tick[0] = 10.
    playing = presentation.compose(target, green_screen=False)
    assert requested == [0]
    assert np.array_equal(playing[HEIGHT//2, WIDTH//2], clip[0, 0])
    assert presentation.marker == {'role_transition_id': 'two-peer-video', 'role_transition_end': False}


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg unavailable")
def test_uploaded_clip_is_fully_decoded_silent_and_protected_while_referenced(tmp_path):
    source = tmp_path / "input.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error",
                    "-f", "lavfi", "-i", "color=blue:size=72x128:rate=25:duration=0.4",
                    "-f", "lavfi", "-i", "sine=frequency=400:duration=0.4",
                    "-c:v", "libx264", "-c:a", "aac", "-shortest", str(source)],
                   check=True, capture_output=True)
    library = TransitionMedia(tmp_path / "clips")
    clip = library.import_file(source, "角色A到B.mp4")
    assert clip["frames"] == 10
    assert clip["silent"] is True
    assert library.list() == [clip]
    with pytest.raises(ProfileError, match="解除轉場設定"):
        library.delete(clip["id"], referenced={clip["id"]})
    with pytest.raises(ProfileError):
        library.get("../input")
    library.delete(clip["id"], referenced=set())
    assert library.list() == []


def test_cancelled_upload_waits_for_worker_and_removes_its_unpublished_asset():
    from src.server.routes.profiles import upload
    async def scenario():
        started, release = Event(), Event()
        deleted, sources = [], []
        def import_file(path, name):
            sources.append(path)
            started.set()
            assert release.wait(2)
            assert path.exists(), 'temporary source was deleted while decoding'
            return {'id': 'abcdef123456'}
        class Part:
            filename = 'clip.mp4'
            sent = False
            async def read_chunk(self, _):
                if self.sent: return b''
                self.sent = True
                return b'fixture'
        class Reader:
            async def next(self): return Part()
        async def multipart(): return Reader()
        roles = SimpleNamespace(media=SimpleNamespace(import_file=import_file,
            delete=lambda asset_id, **_: deleted.append(asset_id)))
        task = asyncio.create_task(upload.__wrapped__(SimpleNamespace(multipart=multipart), roles))
        await asyncio.to_thread(started.wait, 2)
        task.cancel()
        release.set()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError('upload cancellation was swallowed')
        assert deleted == ['abcdef123456']
        assert not sources[0].exists()
    asyncio.run(scenario())
