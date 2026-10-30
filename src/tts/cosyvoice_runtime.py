# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Start and stop the owned local CosyVoice FastAPI process that serves BreezyVoice.

BreezyVoice is a CosyVoice-v1 model with its own text frontend; the process
runs from the ``cosyvoice`` conda environment and the upstream CosyVoice code.
"""
from __future__ import annotations

import atexit
import os
import re
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from src.utils.logging import logger
from src.utils.paths import get_project_root

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 50000
MODELS_ROOT = get_project_root() / "models"
# Every listed file must exist: BreezyVoice ships the CosyVoice v1 YAML plus
# its reading tables; a plain CosyVoice folder is not served.
MODEL_MARKERS = ("cosyvoice.yaml", "word_utils.py")
# Where scripts/breezyvoice_weights.py puts the weights, relative to models/.
DEFAULT_BREEZYVOICE_MODEL_ID = "BreezyVoice"
PROMPT_SAMPLE_RATE = 24000
PROMPT_MAX_SECONDS = 8.0
PROMPT_SCAN_SECONDS = 20.0
PROMPT_SILENCE_THRESHOLD = 0.02
PROMPT_CACHE_SUFFIX = ".cosy24k.v2.wav"

_server_proc: Optional[subprocess.Popen] = None
_loaded_model = ""
_start_lock = threading.Lock()


def default_python() -> Path:
    candidates = [
        Path.home() / "anaconda3" / "envs" / "cosyvoice" / "bin" / "python",
        Path.home() / "miniconda3" / "envs" / "cosyvoice" / "bin" / "python",
        Path("/opt/conda/envs/cosyvoice/bin/python"),
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "找不到 CosyVoice 的 Python。請安裝 conda 環境 cosyvoice，"
        "或設定 COSYVOICE_PYTHON。"
    )


def resolve_python() -> Path:
    override = os.environ.get("COSYVOICE_PYTHON", "").strip()
    if override:
        path = Path(override).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"COSYVOICE_PYTHON 不存在: {path}")
        return path
    return default_python()


def _is_model_dir(directory: Path) -> bool:
    return all((directory / marker).is_file() for marker in MODEL_MARKERS)


def local_models() -> list[dict]:
    """BreezyVoice model folders under ``models/`` (one or two levels deep).

    Settings name a model by its ID here, the folder relative to ``models/``.
    """
    root = MODELS_ROOT
    found = []
    try:
        children = sorted(path for path in root.iterdir() if path.is_dir() and not path.name.startswith("."))
    except OSError:
        return []
    for child in children:
        candidates = [child]
        if not _is_model_dir(child):
            try:
                candidates = sorted(path for path in child.iterdir()
                                    if path.is_dir() and not path.name.startswith("."))
            except OSError:
                continue
        found.extend({"id": directory.relative_to(root).as_posix()}
                     for directory in candidates if _is_model_dir(directory))
    return sorted(found, key=lambda item: item["id"])


def resolve_model_dir(model: str = "") -> Path:
    """The model folder for a ``models/`` catalog ID, or ``models/BreezyVoice``."""
    if model:
        if model not in {item["id"] for item in local_models()}:
            raise FileNotFoundError(f"TTS 模型「{model}」不在 models/ 清單中")
        return MODELS_ROOT / model
    default = MODELS_ROOT / DEFAULT_BREEZYVOICE_MODEL_ID
    if _is_model_dir(default):
        return default
    raise FileNotFoundError(
        f"找不到 BreezyVoice 模型：{default}。"
        "請執行 uv run --no-sync python scripts/breezyvoice_weights.py 下載權重"
    )


def server_url(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> str:
    netloc = f"[{host}]" if ":" in host else host
    return f"http://{netloc}:{int(port)}"


def parse_server_url(url: str) -> tuple[str, int]:
    parsed = urlparse(url or "")
    host = parsed.hostname or DEFAULT_HOST
    port = parsed.port or DEFAULT_PORT
    return host, int(port)


def server_identity(tts_server: str = "", model: str = "") -> tuple[str, int, str]:
    """The BreezyVoice server a voice needs: host, port and model ID, defaults filled in."""
    host, port = parse_server_url(tts_server)
    return host, port, model or DEFAULT_BREEZYVOICE_MODEL_ID


def server_ready(tts_server: str = "", model: str = "") -> bool:
    """Whether a BreezyVoice server with ``model`` already answers at ``tts_server``."""
    try:
        resolved = resolve_model_dir(model)
    except FileNotFoundError:
        return False
    return _health_ok(server_url(*parse_server_url(tts_server)), expected_model=str(resolved))


def prepare_prompt_wav(
    source: str | Path,
    *,
    max_seconds: float = PROMPT_MAX_SECONDS,
    sample_rate: int = PROMPT_SAMPLE_RATE,
    cache_dir: Path | None = None,
) -> Path:
    """Convert a library recording into a short 24 kHz mono prompt WAV."""
    import av
    import numpy as np
    import soundfile as sf

    source_path = Path(source).expanduser()
    if not source_path.is_file():
        raise FileNotFoundError(str(source_path))
    cache_dir = Path(cache_dir) if cache_dir is not None else (
        get_project_root() / "data" / "tts" / "prompts"
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / f"{source_path.stem}{PROMPT_CACHE_SUFFIX}"
    if source_path.name.endswith(PROMPT_CACHE_SUFFIX):
        return source_path
    if (
        dest.is_file()
        and dest.stat().st_mtime >= source_path.stat().st_mtime
        and dest.stat().st_size > 44
    ):
        return dest

    container = av.open(str(source_path))
    try:
        stream = next((item for item in container.streams if item.type == "audio"), None)
        if stream is None:
            raise ValueError(f"沒有音訊軌：{source_path}")
        resampler = av.audio.resampler.AudioResampler(
            format="s16",
            layout="mono",
            rate=sample_rate,
        )
        chunks: list[np.ndarray] = []
        scan_limit = int(max(float(max_seconds), PROMPT_SCAN_SECONDS) * sample_rate)
        collected = 0
        for frame in container.decode(stream):
            for converted in resampler.resample(frame):
                array = converted.to_ndarray().reshape(-1).astype(np.float32) / 32768.0
                remain = scan_limit - collected
                if remain <= 0:
                    break
                if array.size > remain:
                    array = array[:remain]
                chunks.append(array)
                collected += array.size
            if collected >= scan_limit:
                break
        for converted in resampler.resample(None):
            array = converted.to_ndarray().reshape(-1).astype(np.float32) / 32768.0
            remain = scan_limit - collected
            if remain <= 0:
                break
            if array.size > remain:
                array = array[:remain]
            chunks.append(array)
            collected += array.size
    finally:
        container.close()
    if not chunks:
        raise ValueError(f"無法解碼參考音訊：{source_path}")
    audio = trim_prompt_speech(
        np.concatenate(chunks),
        sample_rate,
        max_seconds=max_seconds,
    )
    sf.write(dest, audio, sample_rate, subtype="PCM_16")
    logger.info(
        "BreezyVoice prompt prepared source=%s dest=%s seconds=%.2f",
        source_path,
        dest,
        audio.size / float(sample_rate),
    )
    return dest


def trim_prompt_speech(
    audio,
    sample_rate: int,
    *,
    max_seconds: float = PROMPT_MAX_SECONDS,
    threshold: float = PROMPT_SILENCE_THRESHOLD,
):
    """Drop leading silence, then keep a short spoken window."""
    import numpy as np

    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if samples.size == 0:
        return samples
    frame = max(1, int(sample_rate * 0.02))
    usable = samples[: samples.size - (samples.size % frame)]
    if usable.size == 0:
        return samples[: int(max(0.25, max_seconds) * sample_rate)]
    energy = np.mean(np.abs(usable.reshape(-1, frame)), axis=1)
    active = np.flatnonzero(energy > threshold)
    limit = int(max(0.25, float(max_seconds)) * sample_rate)
    if active.size == 0:
        return samples[:limit]
    start = max(0, int(active[0] * frame) - int(0.12 * sample_rate))
    return samples[start : start + limit]


def _health_payload(url: str):
    try:
        import requests

        response = requests.get(f"{url.rstrip('/')}/health", timeout=2)
        if not response.ok:
            return None
        return response.json()
    except Exception:
        return None


def _health_ok(url: str, expected_model: str = "") -> bool:
    payload = _health_payload(url)
    if not payload or int(payload.get("prompt_prep") or 0) < 3:
        return False
    if not expected_model:
        return True
    reported = str(payload.get("model_dir") or "").strip()
    if not reported:
        return False
    try:
        return Path(reported).resolve() == Path(expected_model).resolve()
    except OSError:
        return reported == expected_model


def _pids_listening_on(port: int) -> list[int]:
    try:
        output = subprocess.check_output(
            ["ss", "-lptn", f"sport = :{int(port)}"],
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        output = ""
    pids = [int(match) for match in re.findall(r"pid=(\d+)", output)]
    return sorted(set(pids))


def _stop_listener(port: int) -> None:
    for pid in _pids_listening_on(port):
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode(
                "utf-8", "replace"
            )
        except OSError:
            continue
        if "cosyvoice_fastapi_server" not in cmdline:
            continue
        logger.info("停止舊的 CosyVoice pid=%s port=%s", pid, port)
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        deadline = time.time() + 8
        while time.time() < deadline:
            if not Path(f"/proc/{pid}").exists():
                break
            time.sleep(0.2)
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def _stop_owned_server() -> None:
    global _server_proc, _loaded_model
    proc = _server_proc
    _server_proc = None
    _loaded_model = ""
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


def shutdown_cosyvoice_server() -> None:
    _stop_owned_server()


def ensure_server(
    *,
    model_dir: str = "",
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout_seconds: float = 180.0,
) -> str:
    """Start the BreezyVoice server if needed and return the HTTP base URL.

    ``model_dir`` is a ``models/`` catalog ID, or empty for ``models/BreezyVoice``.
    Callers (profile apply, console preview) are serialized: one launches, the
    next finds it healthy.
    """
    with _start_lock:
        return _ensure_server(model_dir=model_dir, host=host, port=port, timeout_seconds=timeout_seconds)


def _ensure_server(*, model_dir: str, host: str, port: int, timeout_seconds: float) -> str:
    global _server_proc, _loaded_model
    resolved = resolve_model_dir(model_dir)
    url = server_url(host, port)
    if _health_ok(url, expected_model=str(resolved)) and _loaded_model in {
        "",
        str(resolved),
    }:
        _loaded_model = str(resolved)
        return url
    _stop_owned_server()
    _stop_listener(port)

    python = resolve_python()
    script = get_project_root() / "scripts" / "cosyvoice_fastapi_server.py"
    if not script.is_file():
        raise FileNotFoundError(f"找不到 CosyVoice 啟動腳本: {script}")

    log_path = get_project_root() / "logs" / "cosyvoice-server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("ab")
    cmd = [
        str(python),
        str(script),
        "--host",
        host,
        "--port",
        str(int(port)),
        "--model_dir",
        str(resolved),
    ]
    logger.info("啟動 CosyVoice: %s", " ".join(cmd))
    _server_proc = subprocess.Popen(
        cmd,
        cwd=str(get_project_root()),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    _loaded_model = str(resolved)
    deadline = time.time() + max(15.0, float(timeout_seconds))
    while time.time() < deadline:
        if _server_proc.poll() is not None:
            raise RuntimeError(
                f"CosyVoice 啟動失敗，exit={_server_proc.returncode}。"
                f"請查看 {log_path}"
            )
        if _health_ok(url, expected_model=str(resolved)):
            logger.info("CosyVoice 已就緒: %s model=%s", url, resolved)
            return url
        time.sleep(1.0)
    raise TimeoutError(f"等待 CosyVoice {url} 逾時，請查看 {log_path}")


def install_shutdown_handlers() -> None:
    atexit.register(shutdown_cosyvoice_server)


install_shutdown_handlers()
