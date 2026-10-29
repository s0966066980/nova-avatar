# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""掃描本機 GGUF，並按需拉起 llama-server（OpenAI 相容介面）。"""
from __future__ import annotations

import atexit
import functools
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from src.utils.logging import logger
from src.utils.paths import get_project_root
from src.llm.llamacpp_protocol import LFM_REASONING_BUDGET, is_lfm25_reasoning

_server_proc: Optional[subprocess.Popen] = None
_loaded_model: str = ""
# GPU placement of the llama-server this backend uses: {full, gpu_layers,
# total_layers, error}. None until a launch or reuse has been evaluated.
_gpu_offload: Optional[Dict[str, Any]] = None
# VRAM kept free beyond the weights for KV cache and compute buffers.
GPU_RESERVE_MB = 2048
# ``-ngl`` value that offloads every layer; llama.cpp clamps it to the model.
# An external server started with ``-ngl all`` reads as this value too.
ALL_GPU_LAYERS = 99
NO_USABLE_GPU = "no usable GPU found"


class GpuOffloadError(RuntimeError):
    """llama-server cannot run every layer on the GPU and partial offload is not allowed."""
_CUDA_LIB_NAMES = ("libcudart.so.12", "libcublas.so.12", "libcudart.so.13", "libcublas.so.13")


def default_model_dirs(extra_dir: str = "") -> List[Path]:
    dirs: List[Path] = []
    if extra_dir:
        configured = Path(extra_dir).expanduser()
        if not configured.is_absolute():
            configured = get_project_root() / configured
        dirs.append(configured)
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
    """Locate CUDA runtime libraries on desktop Linux and Jetson."""
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
            Path("/usr/lib/aarch64-linux-gnu"),
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
        # User-local launchers may be symlinks; CUDA libraries sit next to
        # the actual executable, not next to the launcher in ~/.local/bin.
        return Path(which).resolve()
    candidates = [
        get_project_root() / ".local" / "jetson" / "llama.cpp" / "build" / "bin" / "llama-server",
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
            if not gguf.is_file() or 'mmproj' in gguf.name.lower():
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
        return as_path.resolve()
    for item in list_gguf_models(extra_dir):
        if item["name"] == raw or Path(item["path"]).name == raw:
            return Path(item["path"]).resolve()
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
        if values:
            return max(values)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        pass
    # Jetson's nvidia-smi reports memory as Not Supported. Query the driver
    # through PyTorch instead; returning zero would disable all GPU layers.
    try:
        import torch

        if torch.cuda.is_available():
            free_bytes, _total_bytes = torch.cuda.mem_get_info()
            return int(free_bytes // (1024 * 1024))
    except (ImportError, RuntimeError):
        pass
    return 0


def gpu_processes() -> List[Tuple[int, str, int]]:
    """(pid, process name, used MiB) for every GPU compute process, largest first."""
    try:
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,process_name,used_memory",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []
    found: List[Tuple[int, str, int]] = []
    for line in output.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3 or not parts[0].isdigit() or not parts[-1].isdigit():
            continue
        found.append((int(parts[0]), ",".join(parts[1:-1]), int(parts[-1])))
    return sorted(found, key=lambda item: item[2], reverse=True)


def gpu_offload_status() -> Optional[Dict[str, Any]]:
    """Whether the llama-server in use runs every layer on the GPU (None: unknown)."""
    return dict(_gpu_offload) if _gpu_offload is not None else None


def _record_offload(full: bool, gpu_layers: int, total_layers: int, error: str = "") -> None:
    global _gpu_offload
    _gpu_offload = {
        "full": full,
        "gpu_layers": int(gpu_layers),
        "total_layers": int(total_layers),
        "error": error,
    }


def _describe_gpu_holders(limit: int = 6) -> str:
    holders = gpu_processes()[:limit]
    if not holders:
        return "無法取得（nvidia-smi 沒有回報）"
    return "、".join(f"{Path(name).name} (pid {pid}) {used} MiB" for pid, name, used in holders)


_ALLOW_PARTIAL_HINT = (
    "若確定接受較慢的部分卸載，請在設定檔設 llm.llamacpp_allow_partial_offload: true。"
)


def _shortfall_message(gguf: Path, n_layers: int, free_mb: int, ngl: int) -> str:
    model_mb = -(-gguf.stat().st_size // (1024 * 1024))
    need_mb = model_mb + GPU_RESERVE_MB
    return (
        f"顯存不足，llama-server 無法把 {gguf.stem} 的 {n_layers} 層全部放上 GPU："
        f"需要約 {need_mb} MiB（模型 {model_mb} MiB＋{GPU_RESERVE_MB} MiB KV／運算緩衝），"
        f"目前只剩 {free_mb} MiB，只放得下 {ngl} 層。"
        f"目前占用顯存：{_describe_gpu_holders()}。"
        f"請先釋放顯存或改用較小的模型。{_ALLOW_PARTIAL_HINT}"
    )


def _external_gpu_layers(port: int) -> Optional[int]:
    """GPU layer count from the command line of an external llama-server, if stated."""
    for pid in _pids_listening_on(port):
        args = _process_cmdline(pid).split()
        for index, arg in enumerate(args[:-1]):
            if arg in {"-ngl", "--gpu-layers", "--n-gpu-layers"}:
                value = args[index + 1]
                if value == "all":
                    return ALL_GPU_LAYERS
                if value.isdigit():
                    return int(value)
    return None


def _read_from(path: Path, offset: int) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            return handle.read().decode("utf-8", "replace")
    except OSError:
        return ""


def suggest_gpu_layers(model_bytes: int, free_mb: int, n_layers: int) -> int:
    """How many transformer layers can fit in free VRAM, leaving room for KV cache."""
    if free_mb <= 0 or model_bytes <= 0:
        return 0
    layers = max(1, int(n_layers or 64))
    usable_mb = max(0, int(free_mb) - GPU_RESERVE_MB)
    if usable_mb <= 0:
        return 0
    model_mb = model_bytes / (1024 * 1024)
    if usable_mb >= model_mb:
        return ALL_GPU_LAYERS
    per_layer = max(1.0, model_mb / layers)
    return max(0, min(layers, int(usable_mb / per_layer)))


def _offloaded_layers(ngl: int, n_layers: int) -> int:
    """Layers on the GPU for an ``-ngl`` value."""
    return n_layers if ngl >= ALL_GPU_LAYERS else min(ngl, n_layers)


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


def _refreshes_model_info(start: Callable[..., str]) -> Callable[..., str]:
    """Ask the loaded model's context size once, so answers never ask it."""
    @functools.wraps(start)
    def ensure(*args, **kwargs) -> str:
        base_url = start(*args, **kwargs)
        from src.llm.context_usage import deployed_capacity
        deployed_capacity(base_url, refresh=True)
        return base_url
    return ensure


@_refreshes_model_info
def ensure_server(
    model: str,
    *,
    extra_dir: str = "",
    host: str = "127.0.0.1",
    port: int = 8080,
    ctx: int = 2048,
    threads: int = 0,
    allow_partial_offload: bool = False,
) -> str:
    """確保 llama-server 以指定 GGUF 執行，返回 OpenAI base_url。

    預設要求全部層數都在 GPU；放不下時拋出 GpuOffloadError 並說明需要的顯存
    與目前占用者。allow_partial_offload=True 才接受部分（或 CPU）卸載。
    """
    global _server_proc, _loaded_model
    gguf = resolve_gguf(model, extra_dir)
    if gguf is None:
        raise FileNotFoundError(f"找不到 GGUF 模型: {model}")

    status = server_status(host, port)
    if status["running"]:
        same = (status["owned"] and _loaded_model == gguf.stem) or (
            (not status["owned"]) and _same_external_model(host, port, gguf.stem)
        )
        if same and gguf.name == 'gemma-4-E2B_q4_0-it.gguf' and (gguf.parent / 'gemma-4-E2B-it-mmproj.gguf').is_file():
            import requests
            try:
                props = requests.get(f'http://{host}:{int(port)}/props', timeout=2).json()
                same = props.get('modalities', {}).get('vision') is True
            except (requests.RequestException, ValueError):
                same = False
        if same:
            if not status["owned"]:
                n_layers = gguf_block_count(gguf) or 64
                external = _external_gpu_layers(port)
                if external is not None:
                    gpu_layers = _offloaded_layers(external, n_layers)
                    _record_offload(gpu_layers == n_layers, gpu_layers, n_layers)
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
        # LFM 2.5 always thinks. Bound its thinking separately so speech and
        # board data retain room in the shared output token budget.
        "--reasoning",
        "on" if is_lfm25_reasoning(gguf.stem) else "off",
        "--reasoning-budget",
        str(LFM_REASONING_BUDGET) if is_lfm25_reasoning(gguf.stem) else "0",
    ]
    # Only the tested model/projector pairing is automatic. Never attach an
    # arbitrary GGUF from the model directory to another language model.
    if gguf.name == 'gemma-4-E2B_q4_0-it.gguf':
        projector = gguf.parent / 'gemma-4-E2B-it-mmproj.gguf'
        if projector.is_file():
            base_cmd.extend(['--mmproj', str(projector)])
    n_layers = gguf_block_count(gguf) or 64
    if has_cuda_backend(binary):
        free_mb = cuda_free_mb()
        ngl = suggest_gpu_layers(gguf.stat().st_size, free_mb, n_layers)
        if _offloaded_layers(ngl, n_layers) < n_layers:
            message = _shortfall_message(gguf, n_layers, free_mb, ngl)
            if not allow_partial_offload:
                _record_offload(False, 0, n_layers, message)
                raise GpuOffloadError(message)
            logger.warning("%s 已允許部分卸載，改以 %s 層啟動。", message, ngl)
        ngl_tries = (
            [ngl, max(1, ngl // 2), 0] if allow_partial_offload and ngl > 0 else [ngl]
        )
    else:
        message = (
            "這份 llama.cpp 是 CPU 版（沒有 libggml-cuda.so），無法使用 GPU。"
            "請用 GGML_CUDA=ON 重新編譯。"
        )
        if not allow_partial_offload:
            _record_offload(False, 0, n_layers, message)
            raise GpuOffloadError(message + _ALLOW_PARTIAL_HINT)
        ngl_tries = [0]
        logger.warning("%s 大模型會比 GPU 慢很多。", message)

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
        # The log is shared by every launch; mark where this run begins so
        # lines from older runs are not read as the current state.
        log_file.write(
            f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} nova-avatar 啟動 llama-server: "
            f"{' '.join(cmd)} =====\n".encode("utf-8")
        )
        log_file.flush()
        run_offset = log_file.tell()
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
        except Exception as exc:
            last_error = exc
            _stop_owned_server()
            detail = _tail_log(log_path).lower()
            oom = any(token in detail for token in ("out of memory", "cuda malloc", "oom", "insufficient memory"))
            if oom and ngl > 0 and allow_partial_offload:
                logger.warning("llama-server GPU 視訊記憶體不足（ngl=%s），改用更少層重試", ngl)
                continue
            if oom and ngl > 0:
                message = (
                    f"llama-server 以全 GPU 載入 {gguf.stem} 時顯存不足。"
                    f"目前占用顯存：{_describe_gpu_holders()}。{_ALLOW_PARTIAL_HINT}"
                )
                _record_offload(False, 0, n_layers, message)
                raise GpuOffloadError(message) from exc
            raise
        gpu_layers = _offloaded_layers(ngl, n_layers)
        if ngl > 0 and NO_USABLE_GPU in _read_from(log_path, run_offset):
            message = (
                f"llama-server 回報「{NO_USABLE_GPU}」，-ngl 被忽略、全部在 CPU 執行。"
                "請確認 NVIDIA 驅動與 CUDA 函式庫可載入，且 CUDA_VISIBLE_DEVICES 沒有隱藏 GPU。"
            )
            if not allow_partial_offload:
                _stop_owned_server()
                _record_offload(False, 0, n_layers, message)
                raise GpuOffloadError(message + _ALLOW_PARTIAL_HINT)
            logger.warning(message)
            gpu_layers = 0
        _record_offload(gpu_layers >= n_layers, gpu_layers, n_layers)
        if gpu_layers < n_layers:
            logger.warning("llama-server 未全 GPU 執行：%s/%s 層在 GPU", gpu_layers, n_layers)
        return openai_base_url(host, port)
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
    global _server_proc, _loaded_model, _gpu_offload
    if _server_proc is None:
        return
    _gpu_offload = None
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
