# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The avatar rendering layer's entry point: ``AvatarService`` served in-process.

The core reaches the layer (``src.avatars`` and ``src.scene``) only through
this module and ``src.avatars.config_section``; everything else is internal
(import-linter contract ``avatar-internals-private``). Renderers stay in the
core's process (spec decision 1): ``create_renderer`` returns the engine's
renderer, which implements ``AvatarRenderer`` itself.

Functions are looked up on their modules at call time, so a test that
replaces one (for example ``catalog.avatar_bootable``) still takes effect.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Optional

from nova_contracts.avatar import (
    AvatarAssets,
    AvatarBootCheck,
    AvatarRenderer,
    AvatarService,
    FrameSize,
    ImportProgress,
    LoadedAvatarModel,
    ReplaceGuard,
    TransitionClip,
)
from nova_contracts.common import ServiceError
from src.avatars import builder, catalog, mouth_quality, video_output
from src.scene import service as scene


@contextmanager
def _for_operators(*errors: type[Exception]) -> Iterator[None]:
    """Report the layer's own refusals as ``ServiceError`` with the same message."""
    try:
        yield
    except errors as exc:
        raise ServiceError(str(exc)) from exc


class InProcessAvatarService:
    """Model loading, the avatar catalog, imports and the stage scene of this process."""

    # Models and renderers.

    def prepare_model(self, config: Any) -> tuple[LoadedAvatarModel, AvatarAssets]:
        from src.avatars import factory

        return factory.prepare_avatar_model(config)

    def load_assets(self, config: Any) -> AvatarAssets:
        from src.avatars import factory

        return factory.load_avatar_data(config)

    def create_renderer(self, config: Any, model: LoadedAvatarModel, assets: AvatarAssets,
                        sessionid: int) -> AvatarRenderer:
        from src.avatars import factory

        return factory.create_avatar(config, model, assets, sessionid)

    def open_transition_clip(self, path: Path, frames: int) -> TransitionClip:
        from src.scene.role_presentation import TransitionClipReader

        return TransitionClipReader(path, frames)

    # Avatar catalog.

    def list_characters(self) -> list[dict[str, Any]]:
        return catalog.list_avatar_characters()

    def list_engines(self, characters: Optional[list[dict[str, Any]]] = None) -> list[dict[str, Any]]:
        return catalog.list_engines(characters)

    def knows_engine(self, engine: str) -> bool:
        return engine in catalog.ENGINE_META

    def bootable(self, engine: str, avatar_id: str) -> AvatarBootCheck:
        bootable, reason = catalog.avatar_bootable(engine, avatar_id)
        return AvatarBootCheck(bootable=bootable, reason=reason)

    def uses_green_screen(self, avatar_id: str) -> bool:
        return catalog.avatar_uses_green_screen(avatar_id)

    def avatar_exists(self, avatar_id: str) -> bool:
        destination = catalog.avatars_root() / avatar_id
        return destination.exists() or destination.is_symlink()

    def preview_image(self, avatar_id: str) -> Optional[Path]:
        return catalog.resolve_preview_path(avatar_id)

    def source_size(self, avatar_id: str) -> Optional[FrameSize]:
        if not catalog.is_safe_avatar_id(avatar_id):
            return None
        preview = catalog.find_preview_image(catalog.avatars_root() / avatar_id)
        if preview is None:
            return None
        from PIL import Image

        try:
            with Image.open(preview) as image:
                width, height = image.size
        except (OSError, ValueError):
            return None
        return FrameSize(width=width, height=height)

    def archive_avatar(self, avatar_id: str) -> str:
        with _for_operators(ValueError):
            return catalog.archive_avatar(avatar_id).name

    def list_archived_avatars(self) -> list[dict[str, str]]:
        return catalog.list_archived_avatars()

    def restore_avatar(self, archive_name: str) -> str:
        with _for_operators(ValueError):
            return catalog.restore_avatar(archive_name)

    def delete_archived_avatar(self, archive_name: str) -> str:
        with _for_operators(ValueError):
            return catalog.delete_archived_avatar(archive_name)

    # Importing an avatar from a video.

    def can_import(self, engine: str) -> bool:
        return engine in catalog.IMPORTABLE_ENGINES

    def suggest_avatar_id(self, engine: str, source_name: str) -> str:
        return builder.suggest_avatar_id(engine, source_name)

    def uploads_dir(self) -> Path:
        return builder.uploads_dir()

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
        def running_musetalk_vae() -> Any:
            # A MuseTalk model is (vae, unet, pe, timesteps, audio_processor).
            running = running_model() if running_model is not None else None
            if running is None or running[0] != "musetalk" or running[1] is None:
                return None
            return running[1][0]

        with _for_operators(builder.BuildError):
            return builder.build_character(
                engine, video_path, avatar_id,
                overwrite=overwrite, progress=progress,
                quality=dict(quality) if quality is not None else None,
                green_screen=green_screen, replace_guard=replace_guard,
                loaded_vae=running_musetalk_vae,
            )

    # Mouth quality and video output.

    def normalize_quality(self, params: Optional[Mapping[str, Any]]) -> dict[str, Any]:
        with _for_operators(mouth_quality.QualityError):
            return mouth_quality.normalize_quality(params)

    def quality_from_model(self, model: Any) -> dict[str, Any]:
        return mouth_quality.quality_from_model(model)

    def apply_quality(self, model: Any, params: Mapping[str, Any]) -> dict[str, Any]:
        with _for_operators(mouth_quality.QualityError):
            return mouth_quality.apply_quality_to_model(model, params)

    def output_size(self, width: int, height: int, max_height: int = 0) -> FrameSize:
        width, height = video_output.output_dimensions(width, height, max_height)
        return FrameSize(width=width, height=height)

    def records_dir(self) -> Path:
        from src.avatars import base

        return base.RECORDS_DIR

    # Stage scene (green-screen backgrounds).

    @property
    def max_background_bytes(self) -> int:
        return scene.MAX_BACKGROUND_BYTES

    def backgrounds_root(self) -> Path:
        return scene.backgrounds_root()

    def list_backgrounds(self) -> list[dict[str, Any]]:
        return scene.list_backgrounds()

    def add_background(self, path: Path, original_name: str) -> dict[str, Any]:
        with _for_operators(scene.SceneError):
            return scene.add_background(path, original_name)

    def background_preview(self, background_id: str) -> Path:
        with _for_operators(scene.SceneError):
            return scene.preview_path(background_id)

    def archive_background(self, background_id: str) -> str:
        with _for_operators(scene.SceneError):
            return scene.archive_background(background_id).name

    def list_archived_backgrounds(self) -> list[dict[str, str]]:
        return scene.list_archived_backgrounds()

    def restore_background(self, archive_name: str) -> str:
        with _for_operators(scene.SceneError):
            return scene.restore_background(archive_name)

    def scene_snapshot(self) -> dict[str, Any]:
        return scene.scene_service.snapshot()

    def select_background(self, background_id: str) -> dict[str, Any]:
        with _for_operators(scene.SceneError):
            return scene.scene_service.select(background_id)

    def render_avatar_preview(self, avatar_id: str) -> bytes:
        with _for_operators(scene.SceneError):
            return scene.render_avatar_preview(avatar_id)

    def close(self) -> None:
        scene.scene_service.close()


def create_avatar_service() -> AvatarService:
    """The process's avatar rendering layer; the core creates one at startup and shares it."""
    return InProcessAvatarService()


__all__ = ["InProcessAvatarService", "create_avatar_service"]
