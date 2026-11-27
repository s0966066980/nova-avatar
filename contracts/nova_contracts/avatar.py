# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Avatar rendering layer contract (MuseTalk renderer and the stage scene).

The renderer stays in-process (spec decision 1): it shares the media clock,
fences and WebRTC tracks with the core frame by frame, so this module has no
``HTTP_API``. ``AvatarService`` is the process-wide part of the layer (model
loading, the avatar catalog, imports, mouth quality and the stage scene);
``AvatarRenderer`` is one conversation's renderer.

Loaded models and avatar assets are opaque handles: the core keeps them and
hands them back, but never looks inside.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional, Protocol, runtime_checkable

from pydantic import Field

from nova_contracts.common import ContractModel

if TYPE_CHECKING:  # numpy is the caller's dependency, never this package's.
    import numpy as np


class AvatarBootCheck(ContractModel):
    """Whether an engine can start with an avatar; ``reason`` is shown to operators."""

    bootable: bool
    reason: str = ""


class FrameSize(ContractModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)


# The stage canvas role transitions and transition clips are fitted to.
STAGE_FRAME = FrameSize(width=720, height=1280)
STAGE_FPS = 25

# A model loaded by ``AvatarService.prepare_model`` and the assets (frames,
# masks, latents) of one avatar; the core stores and returns them unchanged.
LoadedAvatarModel = Any
AvatarAssets = Any
# Reports import progress: percent (0..100) and a message for operators.
ImportProgress = Callable[[int, str], None]
# Why an existing avatar must not be replaced by an import, or None.
ReplaceGuard = Callable[[str], Optional[str]]


class TransitionClip(Protocol):
    """A role-transition video opened for playback on a renderer."""

    @property
    def frames(self) -> int: ...

    @property
    def failed(self) -> bool: ...

    def close(self) -> None: ...


@runtime_checkable
class AvatarRenderer(Protocol):
    """One conversation's renderer, as the core sees it.

    The core feeds it TTS PCM, fences its media to the current turn, and
    reads its video and audio from the WebRTC tracks it renders into.
    """

    # The session's configuration; the core replaces it when the
    # conversation's settings change (the renderer reads it per frame).
    config: Any

    @property
    def sessionid(self) -> int: ...

    @property
    def chunk(self) -> int:
        """Samples in one 20 ms frame of 16 kHz PCM."""
        ...

    # Speech input and output.

    def put_audio_frame(self, samples: "np.ndarray", eventpoint: dict) -> bool:
        """Queue one 20 ms float32 frame; ``False`` when it was dropped as stale."""
        ...

    def accepts_media(self, eventpoint: dict, stage: str) -> bool: ...

    def flush_talk(self) -> None:
        """Barge-in: drop queued audio and rendered frames of the old reply."""
        ...

    def is_speaking(self) -> bool: ...

    @property
    def direct_audio_enabled(self) -> bool:
        """Whether PCM goes to WebRTC as it arrives instead of after inference."""
        ...

    @property
    def asset_epoch(self) -> int:
        """Bumped by every ``bind_profile``; idle media carries the epoch it was made in."""
        ...

    def notify(self, eventpoint: dict) -> None:
        """A media boundary (speech start, fragment start or end) was played."""
        ...

    def render(self, quit_event: Any, loop: Any = None, audio_track: Any = None,
               video_track: Any = None) -> None:
        """Render into the tracks until ``quit_event`` is set (blocking)."""
        ...

    def configure_media_fence(
        self,
        *,
        media_guard: Callable[[dict, str], bool],
        on_stale_drop: Callable[[str, str], None],
        on_stage_end: Optional[Callable[[str], None]] = None,
    ) -> None: ...

    def configure_pending_audio(self, probe: Callable[[], bool]) -> None:
        """Let the core report whether more reply PCM is on the way."""
        ...

    def configure_audio_output(self, audio_track: Any, loop: Any) -> None: ...

    def set_custom_state(self, audiotype: int, reinit: bool = True) -> None: ...

    # Roles (avatar switching and the transition between two roles).

    def bind_profile(self, config: Any, assets: AvatarAssets) -> None:
        """Swap to another avatar's assets; the tracks and media clock stay."""
        ...

    def reset_role_presentation(self, enabled: bool) -> None:
        """Start a fresh role presentation, or render without one."""
        ...

    def ensure_role_presentation(self) -> None:
        """Keep the current role presentation, or start one if there is none."""
        ...

    def begin_role_transition(self, transition_id: str, edge: Mapping[str, Any], *,
                              clip: Optional[TransitionClip], started_at: float) -> None:
        """Hold the current role on screen until ``started_at``, then play ``edge``."""
        ...

    def start_role_transition(self, started_at: float) -> None:
        """Move the pending transition's start once every peer is bound."""
        ...

    def close_role_transition(self) -> None: ...

    # Recording.

    recording: bool
    width: int
    height: int
    current_record_file: Optional[str]

    def start_recording(self) -> None: ...

    async def stop_recording(self) -> Optional[str]:
        """Finish the recording; the merged file, or ``None`` when nothing was kept."""
        ...

    async def discard_recording(self) -> None: ...


@runtime_checkable
class AvatarService(Protocol):
    """The process-wide avatar rendering layer.

    Expected failures raise ``nova_contracts.common.ServiceError`` with a
    message for operators.
    """

    # Models and renderers.

    def prepare_model(self, config: Any) -> tuple[LoadedAvatarModel, AvatarAssets]:
        """Load (and, unless disabled, warm) the engine and the configured avatar."""
        ...

    def load_assets(self, config: Any) -> AvatarAssets:
        """Load another avatar for the engine that is already loaded."""
        ...

    def create_renderer(self, config: Any, model: LoadedAvatarModel, assets: AvatarAssets,
                        sessionid: int) -> AvatarRenderer: ...

    def open_transition_clip(self, path: Path, frames: int) -> TransitionClip:
        """Start decoding a validated transition clip (blocking up to 2 s)."""
        ...

    # Avatar catalog.

    def list_characters(self) -> list[dict[str, Any]]: ...

    def list_engines(self, characters: Optional[list[dict[str, Any]]] = None) -> list[dict[str, Any]]: ...

    def knows_engine(self, engine: str) -> bool: ...

    def bootable(self, engine: str, avatar_id: str) -> AvatarBootCheck: ...

    def uses_green_screen(self, avatar_id: str) -> bool: ...

    def avatar_exists(self, avatar_id: str) -> bool: ...

    def preview_image(self, avatar_id: str) -> Optional[Path]: ...

    def source_size(self, avatar_id: str) -> Optional[FrameSize]:
        """The size of the avatar's source frames, from its preview image."""
        ...

    def archive_avatar(self, avatar_id: str) -> str:
        """Move an avatar to the recycle bin; returns its archive name."""
        ...

    def list_archived_avatars(self) -> list[dict[str, str]]: ...

    def restore_avatar(self, archive_name: str) -> str: ...

    def delete_archived_avatar(self, archive_name: str) -> str: ...

    # Importing an avatar from a video.

    def can_import(self, engine: str) -> bool: ...

    def suggest_avatar_id(self, engine: str, source_name: str) -> str: ...

    def uploads_dir(self) -> Path: ...

    def build_avatar(
        self,
        engine: str,
        video_path: Path,
        avatar_id: str,
        *,
        overwrite: bool = False,
        progress: Optional[ImportProgress] = None,
        quality: Optional[Mapping[str, Any]] = None,
        green_screen: bool = False,
        replace_guard: Optional[ReplaceGuard] = None,
        running_model: Optional[Callable[[], Optional[tuple[str, LoadedAvatarModel]]]] = None,
    ) -> dict[str, Any]:
        """Build and install an avatar (blocking, minutes).

        ``running_model`` returns the engine type and model the stage is
        running, so a build can borrow its weights instead of loading a copy.
        """
        ...

    # Mouth quality and video output.

    def normalize_quality(self, params: Optional[Mapping[str, Any]]) -> dict[str, Any]: ...

    def quality_from_model(self, model: Any) -> dict[str, Any]: ...

    def apply_quality(self, model: Any, params: Mapping[str, Any]) -> dict[str, Any]:
        """Validate mouth-quality values and write them into the ``model`` section."""
        ...

    def output_size(self, width: int, height: int, max_height: int = 0) -> FrameSize: ...

    def records_dir(self) -> Path:
        """Where finished recordings are kept."""
        ...

    # Stage scene (green-screen backgrounds).

    @property
    def max_background_bytes(self) -> int: ...

    def backgrounds_root(self) -> Path: ...

    def list_backgrounds(self) -> list[dict[str, Any]]: ...

    def add_background(self, path: Path, original_name: str) -> dict[str, Any]: ...

    def background_preview(self, background_id: str) -> Path: ...

    def archive_background(self, background_id: str) -> str:
        """Move a background to the recycle bin; returns its archive name."""
        ...

    def list_archived_backgrounds(self) -> list[dict[str, str]]: ...

    def restore_background(self, archive_name: str) -> str: ...

    def scene_snapshot(self) -> dict[str, Any]: ...

    def select_background(self, background_id: str) -> dict[str, Any]: ...

    def render_avatar_preview(self, avatar_id: str) -> bytes:
        """A JPEG of the avatar on the current stage background."""
        ...

    def close(self) -> None: ...


__all__ = [
    "AvatarAssets",
    "AvatarBootCheck",
    "AvatarRenderer",
    "AvatarService",
    "FrameSize",
    "ImportProgress",
    "LoadedAvatarModel",
    "ReplaceGuard",
    "STAGE_FPS",
    "STAGE_FRAME",
    "TransitionClip",
]
