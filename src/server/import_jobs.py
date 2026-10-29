# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""後臺製作數字人角色的任務佇列。"""
from __future__ import annotations

import shutil
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from src.avatars.builder import (
    BuildError,
    ReplaceGuard,
    build_character,
    suggest_avatar_id,
    uploads_dir,
)
from src.avatars.catalog import IMPORTABLE_ENGINES, avatars_root, is_safe_avatar_id
from src.server.runtime_settings import SettingsError
from src.utils.logging import logger

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv"}


@dataclass
class ImportJob:
    id: str
    engine: str
    avatar_id: str
    status: str = "queued"
    progress: int = 0
    message: str = "排隊中"
    error: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "engine": self.engine,
            "avatar_id": self.avatar_id,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "error": self.error,
            "created_at": self.created_at,
        }


_LOCK = threading.Lock()
_JOBS: Dict[str, ImportJob] = {}
_WORKER_LOCK = threading.Lock()
FINISHED_STATUSES = frozenset({"done", "failed"})
MAX_FINISHED_JOBS = 20
# Only the first MAX_FRAMES frames are used, so a short clip is all an import needs.
MAX_IMPORT_VIDEO_BYTES = 500 * 1024 * 1024
UNEXPECTED_ERROR = "製作角色失敗，請查看伺服器日誌"


def import_in_progress() -> bool:
    return _WORKER_LOCK.locked()


def get_job(job_id: str) -> Optional[ImportJob]:
    with _LOCK:
        return _JOBS.get(job_id)


def validate_import_request(
    *,
    engine: str,
    avatar_id: str,
    original_name: str,
    overwrite: bool,
    session_count: int,
) -> Tuple[str, str]:
    """Check an import before its upload is written; return (engine, avatar_id)."""
    engine = (engine or "").strip().lower()
    if engine not in IMPORTABLE_ENGINES:
        raise SettingsError("請先選擇 MuseTalk 或 Wav2Lip，這兩個引擎才能從影片製作角色")
    if session_count > 0:
        raise SettingsError(
            "製作角色會佔用 GPU，請先斷開當前連線",
            status=409,
            extra={"need_disconnect": True},
        )
    if _WORKER_LOCK.locked():
        raise SettingsError("已有角色正在製作，請稍後再試", status=409)

    chosen_id = (avatar_id or "").strip()
    if not chosen_id:
        chosen_id = suggest_avatar_id(engine, original_name)
    if not is_safe_avatar_id(chosen_id):
        raise SettingsError("角色名稱只能使用字母、數字、下劃線和短橫線")
    destination = avatars_root() / chosen_id
    if not overwrite and (destination.exists() or destination.is_symlink()):
        raise SettingsError(f"角色 {chosen_id} 已存在，請換一個名稱", status=409)
    return engine, chosen_id


def discard_upload(upload_dir: Path) -> None:
    """Remove one request's upload directory under data/imports."""
    if upload_dir.parent == uploads_dir():
        shutil.rmtree(upload_dir, ignore_errors=True)


def start_import_job(
    *,
    engine: str,
    video_path: Path,
    original_name: str,
    avatar_id: str = "",
    overwrite: bool = False,
    session_count: int = 0,
    quality: Optional[Dict[str, Any]] = None,
    green_screen: bool = False,
    replace_guard: ReplaceGuard = None,
) -> ImportJob:
    engine, chosen_id = validate_import_request(
        engine=engine,
        avatar_id=avatar_id,
        original_name=original_name,
        overwrite=overwrite,
        session_count=session_count,
    )
    # The job owns the worker lock from here until _run_job finishes.
    if not _WORKER_LOCK.acquire(blocking=False):
        raise SettingsError("已有角色正在製作，請稍後再試", status=409)
    try:
        job = ImportJob(id=uuid.uuid4().hex[:12], engine=engine, avatar_id=chosen_id)
        with _LOCK:
            _prune_finished_jobs()
            _JOBS[job.id] = job
        thread = threading.Thread(
            target=_run_job,
            args=(job, video_path, overwrite, quality, green_screen, replace_guard),
            daemon=True,
            name=f"avatar-import-{job.id}",
        )
        thread.start()
    except BaseException:
        _WORKER_LOCK.release()
        raise
    return job


def _prune_finished_jobs() -> None:
    finished = [job_id for job_id, job in _JOBS.items() if job.status in FINISHED_STATUSES]
    for job_id in finished[: max(0, len(finished) - MAX_FINISHED_JOBS + 1)]:
        del _JOBS[job_id]


def _run_job(
    job: ImportJob,
    video_path: Path,
    overwrite: bool,
    quality: Optional[Dict[str, Any]] = None,
    green_screen: bool = False,
    replace_guard: ReplaceGuard = None,
) -> None:
    def progress(percent: int, message: str) -> None:
        job.progress = max(0, min(100, int(percent)))
        job.message = message
        job.status = "running"

    job.status = "running"
    job.message = "開始製作"
    try:
        build_character(
            job.engine,
            video_path,
            job.avatar_id,
            overwrite=overwrite,
            progress=progress,
            quality=quality,
            green_screen=green_screen,
            replace_guard=replace_guard,
        )
        job.status = "done"
        job.progress = 100
        job.message = "角色製作完成"
    except BuildError as exc:
        job.status = "failed"
        job.error = str(exc)
        job.message = str(exc)
        logger.warning(f"製作角色失敗: {exc}")
    except Exception:
        # Unexpected errors can carry absolute paths; keep them in the server log.
        job.status = "failed"
        job.error = UNEXPECTED_ERROR
        job.message = job.error
        logger.exception("製作角色失敗")
    finally:
        try:
            if video_path.exists():
                video_path.unlink()
            parent = video_path.parent
            if parent.is_dir() and parent.parent == uploads_dir() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass
        finally:
            _WORKER_LOCK.release()
