# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Start, stop and call the owned Fun-ASR-Nano-2512 recognition service.

The service (``scripts/fun_asr_nano_server.py``) runs from its own venv
(``scripts/setup-fun-asr-nano.sh``), binds loopback only and is started when
the FunASR engine loads, i.e. only while FunASR is the selected engine.
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

from src.utils.logging import logger
from src.utils.paths import get_project_root

# DEFAULT_PORT, FAMILY and OUTPUT_SCRIPTS are also defined in
# scripts/fun_asr_nano_server.py, which runs in its own venv and cannot import
# src; tests/test_funasr.py keeps the two in agreement.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 50010
FAMILY = "fun-asr-nano"
# Output scripts the service accepts; OpenCC s2twp gives Taiwan Traditional.
OUTPUT_SCRIPTS = ("traditional-tw", "simplified")
# Settings name a model by ID; the folder is models/funasr/<ID>.
MODEL_IDS = ("Fun-ASR-Nano-2512",)
DEFAULT_MODEL = MODEL_IDS[0]
# Saved settings that still name the removed Paraformer model load Fun-ASR-Nano.
LEGACY_MODEL_IDS = frozenset({"paraformer-zh"})
MODELS_ROOT = get_project_root() / "models"
REQUIRED_MODEL_FILES = (
    "config.yaml",
    "configuration.json",
    "model.pt",
    "multilingual.tiktoken",
    "Qwen3-0.6B/config.json",
    "Qwen3-0.6B/tokenizer.json",
    "Qwen3-0.6B/tokenizer_config.json",
)
SERVER_SCRIPT = get_project_root() / "scripts" / "fun_asr_nano_server.py"
LOG_PATH = get_project_root() / "logs" / "fun-asr-nano-server.log"
DEFAULT_PYTHON = Path.home() / ".venvs" / "fun-asr-nano" / "bin" / "python"
SETUP_HINT = "執行 bash scripts/setup-fun-asr-nano.sh 建立 Fun-ASR-Nano venv"
WEIGHTS_HINT = "執行 uv run --no-sync python scripts/fun_asr_nano_weights.py 下載權重"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

_lock = threading.RLock()
_server_proc: Optional[subprocess.Popen] = None
# Set by stop_server() so a start holding _lock gives up instead of loading on.
_start_cancelled = threading.Event()


def resolve_model(name: str) -> str:
    """The model ID for a setting; anything off the list is refused."""
    requested = str(name or DEFAULT_MODEL).strip()
    if requested in MODEL_IDS:
        return requested
    if requested in LEGACY_MODEL_IDS:
        logger.warning("FunASR 模型 %s 已移除，改用 %s", requested, DEFAULT_MODEL)
        return DEFAULT_MODEL
    raise ValueError(f"不支援的 FunASR 模型: {requested}")


def model_dir(name: str = DEFAULT_MODEL) -> Path:
    return MODELS_ROOT / "funasr" / resolve_model(name)


def model_ready(name: str = DEFAULT_MODEL) -> bool:
    folder = model_dir(name)
    return all((folder / item).is_file() for item in REQUIRED_MODEL_FILES)


def resolve_python() -> Path:
    override = os.environ.get("FUN_ASR_NANO_PYTHON", "").strip()
    path = Path(override).expanduser() if override else DEFAULT_PYTHON
    if not path.is_file():
        raise FileNotFoundError(f"找不到 Fun-ASR-Nano 的 Python：{path}。{SETUP_HINT}")
    return path


def unavailable_reason(name: str = DEFAULT_MODEL) -> str:
    """Why FunASR cannot start, or ``""`` when its venv and weights are present."""
    try:
        resolve_python()
    except FileNotFoundError as exc:
        return str(exc)
    if not model_ready(name):
        return f"找不到 Fun-ASR-Nano 權重：{model_dir(name)}。{WEIGHTS_HINT}"
    return ""


def server_url(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> str:
    netloc = f"[{host}]" if ":" in host else host
    return f"http://{netloc}:{int(port)}"


def _health_payload(url: str) -> Optional[dict]:
    try:
        import requests

        response = requests.get(f"{url}/health", timeout=2)
        return response.json() if response.ok else None
    except Exception:
        return None


def _health_matches(payload: Optional[dict], folder: Path, device: str) -> bool:
    if not payload or payload.get("family") != FAMILY:
        return False
    if payload.get("requested_device") != device:
        return False
    try:
        return Path(str(payload.get("model_dir") or "")).resolve() == folder.resolve()
    except OSError:
        return False


def _owned_script_pids(port: int) -> list[int]:
    """Listeners on ``port`` that run this checkout's service script."""
    try:
        output = subprocess.check_output(["ss", "-lptn", f"sport = :{int(port)}"], text=True, timeout=3)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []
    pids = []
    for pid in sorted({int(match) for match in re.findall(r"pid=(\d+)", output)}):
        try:
            args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if os.fsencode(str(SERVER_SCRIPT)) in args:
            pids.append(pid)
    return pids


def _stop_stale_listener(port: int) -> None:
    for pid in _owned_script_pids(port):
        logger.info("停止舊的 Fun-ASR-Nano 服務 pid=%s port=%s", pid, port)
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        deadline = time.time() + 8
        while time.time() < deadline and Path(f"/proc/{pid}").exists():
            time.sleep(0.2)
        if Path(f"/proc/{pid}").exists():
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def shutdown_fun_asr_server() -> None:
    """Stop the service this backend started (backend exit)."""
    global _server_proc
    with _lock:
        proc, _server_proc = _server_proc, None
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


def stop_server(port: int = DEFAULT_PORT) -> None:
    """Free the GPU when another engine is selected, including a service left by an earlier backend.

    A start in progress is cancelled rather than waited out (it may take minutes).
    """
    _start_cancelled.set()
    with _lock:
        _start_cancelled.clear()
        shutdown_fun_asr_server()
        _stop_stale_listener(port)


def _abort_if_cancelled() -> None:
    if _start_cancelled.is_set():
        shutdown_fun_asr_server()
        raise RuntimeError("Fun-ASR-Nano 啟動已取消：已改選其他語音辨識引擎")


def ensure_server(
    *,
    model: str = DEFAULT_MODEL,
    device: str = "auto",
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout_seconds: float = 300.0,
) -> str:
    """Start the service for ``model`` on ``device`` if needed; return its base URL."""
    global _server_proc
    if host not in LOOPBACK_HOSTS:
        raise ValueError(f"Fun-ASR-Nano 服務只綁本機位址（loopback），收到 {host}")
    folder = model_dir(model)
    url = server_url(host, port)
    with _lock:
        if _health_matches(_health_payload(url), folder, device):
            return url
        shutdown_fun_asr_server()
        _stop_stale_listener(port)
        python = resolve_python()
        if not model_ready(model):
            raise FileNotFoundError(f"找不到 Fun-ASR-Nano 權重：{folder}。{WEIGHTS_HINT}")
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        command = [str(python), str(SERVER_SCRIPT), "--host", host, "--port", str(int(port)),
                   "--model_dir", str(folder), "--device", device]
        logger.info("啟動 Fun-ASR-Nano: %s", " ".join(command))
        with LOG_PATH.open("ab") as log_file:
            proc = subprocess.Popen(command, cwd=str(get_project_root()), stdout=log_file,
                                    stderr=subprocess.STDOUT, start_new_session=True)
        _server_proc = proc
        deadline = time.time() + max(15.0, float(timeout_seconds))
        while time.time() < deadline:
            _abort_if_cancelled()
            if proc.poll() is not None:
                _server_proc = None
                raise RuntimeError(f"Fun-ASR-Nano 啟動失敗，exit={proc.returncode}。請查看 {LOG_PATH}")
            if _health_matches(_health_payload(url), folder, device):
                logger.info("Fun-ASR-Nano 已就緒: %s model=%s device=%s", url, folder, device)
                return url
            time.sleep(1.0)
        shutdown_fun_asr_server()
        raise TimeoutError(f"等待 Fun-ASR-Nano {url} 逾時，請查看 {LOG_PATH}")


def recognize(url: str, pcm16: bytes, *, language: str, script: str, timeout: float = 60.0) -> dict:
    """Recognize 16 kHz mono PCM16 audio; returns ``{"text", "language"}``."""
    import requests

    response = requests.post(
        f"{url}/recognize",
        params={"language": language, "script": script},
        data=pcm16,
        headers={"Content-Type": "application/octet-stream"},
        timeout=timeout,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not response.ok:
        raise RuntimeError(f"Fun-ASR-Nano 辨識失敗 HTTP {response.status_code}: {payload.get('error', '')}")
    return {"text": str(payload.get("text", "")), "language": str(payload.get("language", ""))}


atexit.register(shutdown_fun_asr_server)
