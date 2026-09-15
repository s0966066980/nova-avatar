# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""掃描本機 GGUF，並按需拉起 llama-server（OpenAI 相容介面）。"""
from __future__ import annotations

import atexit
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from src.utils.logging import logger
from src.utils.paths import get_project_root

_server_proc: Optional[subprocess.Popen] = None
_loaded_model: str = ""
_CUDA_LIB_NAMES = ("libcudart.so.12", "libcublas.so.12")


def default_model_dirs(extra_dir: str = "") -> List[Path]:
    dirs: List[Path] = []
    if extra_dir:
        dirs.append(Path(extra_dir).expanduser())
    dirs.append(get_project_root() / "llama")
    dirs.append(Path.home() / "llama")
    seen = set()
    unique = []
    for path in dirs:
        resolved = path.resolve() if path.exists() else path
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def has_cuda_backend(binary: Optional[Path] = None) -> bool:
    path = binary or find_llama_server()
    if path is None:
        return False
    return (path.parent / "libggml-cuda.so").is_file() or (path.parent / "libggml-cuda.so.0").is_file()


def cuda_library_dirs(extra_roots: Optional[Iterable[Path]] = None) -> List[Path]:
    """Locate directories that contain CUDA 12 runtime libs needed by llama-server."""
    roots: List[Path] = []
    if extra_roots:
        roots.extend(Path(p) for p in extra_roots)
    for key in ("CUDA_HOME", "CUDA_PATH"):
        value = os.environ.get(key)
        if value:
            roots.append(Path(value) / "lib64")
            roots.append(Path(value) / "lib")
    roots.extend(
        [
            Path("/usr/local/cuda/lib64"),
            Path("/usr/local/cuda/lib"),
            Path("/usr/local/lib/ollama/cuda_v12"),
            Path("/usr/lib/x86_64-linux-gnu"),
        ]
    )
    try:
        import nvidia

        nvidia_root = Path(nvidia.__file__).resolve().parent
        for sub in ("cuda_runtime/lib", "cublas/lib"):
            roots.append(nvidia_root / sub)
    except Exception:
        pass
    prefix = Path(sys.prefix)
    roots.extend(prefix.glob("lib/python*/site-packages/nvidia/*/lib"))

    found: List[Path] = []
    seen = set()
    for root in roots:
        if not root.is_dir():
            continue
        key = str(root.resolve())
        if key in seen:
            continue
        if any((root / name).is_file() for name in _CUDA_LIB_NAMES):
            seen.add(key)
            found.append(root)
    return found


def build_server_env(binary: Path) -> Dict[str, str]:
    env = os.environ.copy()
    lib_dirs = [str(binary.parent), *[str(path) for path in cuda_library_dirs()]]
    existing = env.get("LD_LIBRARY_PATH", "")
    if existing:
        lib_dirs.append(existing)
    env["LD_LIBRARY_PATH"] = ":".join(lib_dirs)
    return env


def find_llama_server() -> Optional[Path]:
    which = shutil.which("llama-server")
    if which:
        return Path(which)
    candidates = [
        Path.home() / "llama" / "llama.cpp" / "build" / "bin" / "llama-server",
        get_project_root() / "llama" / "llama.cpp" / "build" / "bin" / "llama-server",
        Path.home() / "llama.cpp" / "build" / "bin" / "llama-server",
    ]
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


def list_gguf_models(extra_dir: str = "") -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    seen = set()
    for folder in default_model_dirs(extra_dir):
        if not folder.is_dir():
            continue
        for gguf in sorted(folder.glob("*.gguf")):
            if not gguf.is_file():
                continue
            key = str(gguf.resolve())
            if key in seen:
                continue
            seen.add(key)
            size = gguf.stat().st_size
            items.append(
                {
                    "name": gguf.stem,
                    "path": str(gguf),
                    "size": size,
                    "size_label": _format_bytes(size),
                    "family": "gguf",
                    "parameter_size": "",
                }
            )
    return items


def resolve_gguf(model: str, extra_dir: str = "") -> Optional[Path]:
    raw = (model or "").strip()
    if not raw:
        return None
    as_path = Path(raw).expanduser()
    if as_path.is_file() and as_path.suffix.lower() == ".gguf":
        return as_path
    for item in list_gguf_models(extra_dir):
        if item["name"] == raw or Path(item["path"]).name == raw:
            return Path(item["path"])
    return None


def openai_base_url(host: str = "127.0.0.1", port: int = 8080) -> str:
    return f"http://{host}:{int(port)}/v1"


def server_status(host: str = "127.0.0.1", port: int = 8080) -> Dict[str, Any]:
    import urllib.error
    import urllib.request

    url = f"http://{host}:{int(port)}/health"
    try:
        with urllib.request.urlopen(url, timeout=1.5) as resp:
            ok = 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        ok = False
    return {
        "running": ok,
        "owned": _server_proc is not None and _server_proc.poll() is None,
        "loaded_model": _loaded_model,
        "base_url": openai_base_url(host, port),
        "binary": str(find_llama_server()) if find_llama_server() else "",
    }


def gguf_block_count(path: Path) -> int:
    """Read *.block_count from a GGUF header. 0 if the file cannot be parsed."""
    try:
        with path.open("rb") as handle:
            if handle.read(4) != b"GGUF":
                return 0
            struct.unpack("<I", handle.read(4))
            _n_tensors, n_kv = struct.unpack("<QQ", handle.read(16))

            def read_string() -> str:
                size = struct.unpack("<Q", handle.read(8))[0]
                return handle.read(size).decode("utf-8", "replace")

            def skip(kind: int) -> None:
                if kind in {0, 1, 7}:
                    handle.read(1)
                elif kind in {2, 3}:
                    handle.read(2)
                elif kind in {4, 5, 6}:
                    handle.read(4)
                elif kind in {10, 11, 12}:
                    handle.read(8)
                elif kind == 8:
                    handle.read(struct.unpack("<Q", handle.read(8))[0])
                elif kind == 9:
                    inner = struct.unpack("<I", handle.read(4))[0]
                    count = struct.unpack("<Q", handle.read(8))[0]
                    for _ in range(count):
                        skip(inner)

            for _ in range(n_kv):
                key = read_string()
                kind = struct.unpack("<I", handle.read(4))[0]
                if key.endswith(".block_count"):
                    if kind == 4:
                        return int(struct.unpack("<I", handle.read(4))[0])
                    if kind == 5:
                        return int(struct.unpack("<i", handle.read(4))[0])
                    if kind == 10:
                        return int(struct.unpack("<Q", handle.read(8))[0])
                    if kind == 11:
                        return int(struct.unpack("<q", handle.read(8))[0])
                    skip(kind)
                    return 0
                skip(kind)
    except (OSError, struct.error, UnicodeDecodeError):
        return 0
    return 0


def cuda_free_mb() -> int:
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            text=True,
            timeout=5,
        )
        values = [int(line.strip()) for line in output.splitlines() if line.strip().isdigit()]
        return max(values) if values else 0
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        return 0


def suggest_gpu_layers(model_bytes: int, free_mb: int, n_layers: int) -> int:
    """How many transformer layers can fit in free VRAM, leaving room for KV cache."""
    if free_mb <= 0 or model_bytes <= 0:
        return 0
    layers = max(1, int(n_layers or 64))
    usable_mb = max(0, int(free_mb) - 2048)
    if usable_mb <= 0:
        return 0
    model_mb = model_bytes / (1024 * 1024)
    if usable_mb >= model_mb:
        return 99
    per_layer = max(1.0, model_mb / layers)
    return max(0, min(layers, int(usable_mb / per_layer)))


def _pids_listening_on(port: int) -> List[int]:
    port = int(port)
    try:
        output = subprocess.check_output(
            ["ss", "-lptn", f"sport = :{port}"],
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        output = ""
    pids = [int(match) for match in re.findall(r"pid=(\d+)", output)]
    if pids:
        return sorted(set(pids))
    try:
        output = subprocess.check_output(
            ["lsof", "-ti", f"TCP:{port}", "-sTCP:LISTEN"],
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []
    return sorted({int(item) for item in output.split() if item.isdigit()})


def _process_cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode(
            "utf-8", "replace"
        )
    except OSError:
        return ""


def stop_llama_on_port(port: int) -> None:
    """Stop a leftover llama-server on our configured port so settings can switch GGUF."""
    for pid in _pids_listening_on(port):
        cmdline = _process_cmdline(pid)
        if "llama-server" not in cmdline:
            raise RuntimeError(
                f"埠 {port} 已被其他程式佔用，無法切換模型：{cmdline[:120] or pid}"
            )
        logger.info("停止佔用埠 %s 的 llama-server pid=%s", port, pid)
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


def ensure_server(
    model: str,
    *,
    extra_dir: str = "",
    host: str = "127.0.0.1",
    port: int = 8080,
    ctx: int = 2048,
    threads: int = 0,
) -> str:
    """確保 llama-server 以指定 GGUF 執行，返回 OpenAI base_url。"""
    global _server_proc, _loaded_model
    gguf = resolve_gguf(model, extra_dir)
    if gguf is None:
        raise FileNotFoundError(f"找不到 GGUF 模型: {model}")

    status = server_status(host, port)
    if status["running"]:
        same = (status["owned"] and _loaded_model == gguf.stem) or (
            (not status["owned"]) and _same_external_model(host, port, gguf.stem)
        )
        if same:
            return openai_base_url(host, port)
        if status["owned"]:
            _stop_owned_server()
        else:
            stop_llama_on_port(port)
    else:
        _stop_owned_server()

    binary = find_llama_server()
    if binary is None:
        raise FileNotFoundError(
            "找不到 llama-server。請安裝 llama.cpp，或把它放到 ~/llama/llama.cpp/build/bin/"
        )

    env = build_server_env(binary)
    cpu_threads = threads if threads and threads > 0 else (os.cpu_count() or 8)
    base_cmd = [
        str(binary),
        "-m",
        str(gguf),
        "--host",
        host,
        "--port",
        str(int(port)),
        "-c",
        str(max(512, int(ctx or 2048))),
        "-t",
        str(cpu_threads),
        "-b",
        "2048",
        "-ub",
        "512",
        "-fa",
        "on",
        "-ctk",
        "q8_0",
        "-ctv",
        "q8_0",
        # LFM 等帶思考鏈的模型會把 max_tokens 全耗在 reasoning_content 上
        "--reasoning",
        "off",
        "--reasoning-budget",
        "0",
    ]
    n_layers = gguf_block_count(gguf) or 64
    if has_cuda_backend(binary):
        ngl = suggest_gpu_layers(gguf.stat().st_size, cuda_free_mb(), n_layers)
        ngl_tries = [ngl] if ngl <= 0 else [ngl, max(1, ngl // 2), 0]
    else:
        ngl_tries = [0]
        logger.warning(
            "這份 llama.cpp 是 CPU 版（沒有 libggml-cuda.so）。"
            "大模型會比 GPU 慢很多。請用 GGML_CUDA=ON 重新編譯後再套用模型。"
        )

    log_path = get_project_root() / "logs" / "llama-server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timeout = 180 if gguf.stat().st_size >= 8 * 1024**3 else 120
    last_error: Optional[Exception] = None
    seen_ngl = set()
    for ngl in ngl_tries:
        if ngl in seen_ngl:
            continue
        seen_ngl.add(ngl)
        cmd = list(base_cmd)
        if ngl > 0:
            cmd.extend(["-ngl", str(ngl)])
            logger.info("llama-server 使用 CUDA 解除安裝 %s 層", ngl)
        log_file = log_path.open("ab")
        logger.info("啟動 llama-server: %s", " ".join(cmd))
        _server_proc = subprocess.Popen(
            cmd,
            cwd=str(binary.parent),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        _loaded_model = gguf.stem
        try:
            _wait_until_ready(host, port, timeout=timeout, log_path=log_path)
            return openai_base_url(host, port)
        except Exception as exc:
            last_error = exc
            _stop_owned_server()
            detail = _tail_log(log_path).lower()
            oom = any(token in detail for token in ("out of memory", "cuda malloc", "oom", "insufficient memory"))
            if oom and ngl > 0:
                logger.warning("llama-server GPU 視訊記憶體不足（ngl=%s），改用更少層重試", ngl)
                continue
            raise
    raise last_error or RuntimeError("無法啟動 llama-server")


def _same_external_model(host: str, port: int, stem: str) -> bool:
    import json
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://{host}:{int(port)}/v1/models", timeout=2) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return False
    for item in payload.get("data") or []:
        name = str(item.get("id") or "")
        if stem in name or name in {stem, f"{stem}.gguf"}:
            return True
    return False


def _wait_until_ready(
    host: str, port: int, timeout: int = 120, log_path: Optional[Path] = None
) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _server_proc is not None and _server_proc.poll() is not None:
            detail = _tail_log(log_path)
            suffix = f"：{detail}" if detail else "，請檢視 logs/llama-server.log"
            raise RuntimeError(f"llama-server 啟動後立刻退出{suffix}")
        if server_status(host, port)["running"]:
            logger.info("llama-server 已就緒 %s:%s", host, port)
            return
        time.sleep(1)
    raise TimeoutError("等待 llama-server 就緒超時")


def _tail_log(path: Optional[Path], n: int = 6) -> str:
    if path is None:
        return ""
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return ""
    return " | ".join(line.strip() for line in lines[-n:] if line.strip())


def _stop_owned_server() -> None:
    global _server_proc, _loaded_model
    if _server_proc is None:
        return
    if _server_proc.poll() is None:
        _server_proc.terminate()
        try:
            _server_proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            _server_proc.kill()
    _server_proc = None
    _loaded_model = ""


def shutdown_llama_server() -> None:
    """Stop only the llama-server process started by this application.

    An externally managed server is deliberately left untouched.  The helper
    is safe to call from shutdown hooks more than once.
    """
    _stop_owned_server()


def install_shutdown_handlers() -> None:
    """Ensure Ctrl-C/termination also releases an owned llama-server."""
    def _handle_shutdown(signum, _frame):
        logger.info("收到關閉訊號 %s，正在停止 llama-server", signum)
        shutdown_llama_server()
        raise SystemExit(128 + int(signum))

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, _handle_shutdown)


atexit.register(shutdown_llama_server)


def _has_cuda() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:
        return False


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} {unit}" if unit in {"B", "KB"} else f"{value:.1f} {unit}"
        value /= 1024
    return ""
