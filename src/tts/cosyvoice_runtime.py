# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Start and stop an owned local CosyVoice FastAPI process."""
from __future__ import annotations

import atexit
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from src.utils.logging import logger
from src.utils.paths import get_project_root

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 50000
DEFAULT_MODEL_DIR = Path.home() / "CosyVoice" / "pretrained_models" / "CosyVoice2-0.5B"
DEFAULT_COSYVOICE3_MODEL_DIRS = (
    Path.home() / "CosyVoice" / "pretrained_models" / "Fun-CosyVoice3-0.5B",
    Path.home() / "CosyVoice" / "pretrained_models" / "Fun-CosyVoice3-0.5B-2512",
    Path("/home/oliver/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B"),
    Path("/home/oliver/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B-2512"),
)
DEFAULT_PROMPT_WAV = get_project_root() / "data" / "tts" / "cosyvoice_prompt.wav"
DEFAULT_PROMPT_TEXT = "你好，我是數字人助手。"
COSYVOICE_ENGINES = frozenset({"cosyvoice", "fun-cosyvoice3"})
COSYVOICE_LANGUAGE_INSTRUCT = {
    "zh": "用中文说这句话",
    "chinese": "用中文说这句话",
    "en": "Speak this in English",
    "english": "Speak this in English",
    "ja": "日本語で話してください",
    "japanese": "日本語で話してください",
    "ko": "한국어로 말해 주세요",
    "korean": "한국어로 말해 주세요",
    "yue": "用广东话说这句话",
    "auto": "",
}
COSYVOICE3_LANGUAGE_INSTRUCT = {
    "zh": "请用中文说这句话。",
    "chinese": "请用中文说这句话。",
    "en": "Please speak this in English.",
    "english": "Please speak this in English.",
    "ja": "日本語で話してください。",
    "japanese": "日本語で話してください。",
    "ko": "한국어로 말해 주세요.",
    "korean": "한국어로 말해 주세요.",
    "de": "Bitte sprechen Sie dies auf Deutsch.",
    "es": "Por favor hable esto en español.",
    "fr": "Veuillez dire ceci en français.",
    "it": "Per favore dillo in italiano.",
    "ru": "Пожалуйста, скажите это по-русски.",
    "yue": "请用广东话表达。",
    "auto": "",
}
COSYVOICE_LANGUAGES = (
    ("zh", "中文"),
    ("en", "English"),
    ("ja", "日本語"),
    ("ko", "한국어"),
    ("yue", "粵語"),
    ("auto", "自動"),
)
COSYVOICE3_LANGUAGES = (
    ("zh", "中文"),
    ("en", "English"),
    ("ja", "日本語"),
    ("ko", "한국어"),
    ("yue", "粵語"),
    ("de", "Deutsch"),
    ("es", "Español"),
    ("fr", "Français"),
    ("it", "Italiano"),
    ("ru", "Русский"),
    ("auto", "自動"),
)
PROMPT_SAMPLE_RATE = 24000
PROMPT_MAX_SECONDS = 8.0
PROMPT_SCAN_SECONDS = 20.0
PROMPT_SILENCE_THRESHOLD = 0.02
PROMPT_CACHE_SUFFIX = ".cosy24k.v2.wav"

_server_proc: Optional[subprocess.Popen] = None
_loaded_model = ""


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


def is_cosyvoice_engine(engine: str) -> bool:
    return str(engine or "").strip().lower() in COSYVOICE_ENGINES


def cosyvoice_family(engine: str) -> str:
    if str(engine or "").strip().lower() == "fun-cosyvoice3":
        return "cosyvoice3"
    return "cosyvoice2"


def languages_for_family(family: str):
    if family == "cosyvoice3":
        return COSYVOICE3_LANGUAGES
    return COSYVOICE_LANGUAGES


def resolve_model_dir(model: str = "", family: str = "cosyvoice2") -> Path:
    if model:
        path = Path(model).expanduser()
        if path.is_dir():
            return path
        name = path.name
        if name:
            for folder in (
                Path.home() / "CosyVoice" / "pretrained_models",
                Path("/home/oliver/CosyVoice/pretrained_models"),
            ):
                candidate = folder / name
                if candidate.is_dir():
                    return candidate
    candidates = (
        DEFAULT_COSYVOICE3_MODEL_DIRS
        if family == "cosyvoice3"
        else (DEFAULT_MODEL_DIR,)
    )
    for path in candidates:
        if path.is_dir():
            return path
    expected = candidates[0]
    if family == "cosyvoice3":
        raise FileNotFoundError(
            f"找不到 Fun-CosyVoice 3.0 模型：{model or expected}。"
            "請下載 FunAudioLLM/Fun-CosyVoice3-0.5B-2512 到 "
            "~/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B"
        )
    raise FileNotFoundError(
        f"找不到 CosyVoice 模型目錄: {model or DEFAULT_MODEL_DIR}"
    )


def server_url(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> str:
    return f"http://{host}:{int(port)}"


def normalize_language(value: str, family: str = "cosyvoice2") -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "zh-tw": "zh",
        "zh-cn": "zh",
        "cn": "zh",
        "jp": "ja",
        "kr": "ko",
        "cantonese": "yue",
        "german": "de",
        "spanish": "es",
        "french": "fr",
        "italian": "it",
        "russian": "ru",
    }
    raw = aliases.get(raw, raw)
    mapping = {
        "chinese": "zh",
        "english": "en",
        "japanese": "ja",
        "korean": "ko",
    }
    raw = mapping.get(raw, raw)
    table = (
        COSYVOICE3_LANGUAGE_INSTRUCT
        if family == "cosyvoice3"
        else COSYVOICE_LANGUAGE_INSTRUCT
    )
    if raw in table:
        return raw
    if raw in COSYVOICE_LANGUAGE_INSTRUCT or raw in COSYVOICE3_LANGUAGE_INSTRUCT:
        return raw
    return "zh"


def build_instruct(
    language: str,
    extra: str = "",
    *,
    family: str = "cosyvoice2",
) -> str:
    """instruct2 text that can force spoken language for CosyVoice 2/3."""
    lang = normalize_language(language, family=family)
    table = (
        COSYVOICE3_LANGUAGE_INSTRUCT
        if family == "cosyvoice3"
        else COSYVOICE_LANGUAGE_INSTRUCT
    )
    extra_text = str(extra or "").replace("<|endofprompt|>", "").strip()
    parts = []
    lang_text = table.get(lang, "")
    if lang_text:
        parts.append(lang_text)
    if extra_text:
        parts.append(extra_text)
    if not parts:
        return ""
    if family == "cosyvoice3":
        body = " ".join(parts)
        if not body.startswith("You are a helpful assistant"):
            body = f"You are a helpful assistant. {body}"
        return body.rstrip() + "<|endofprompt|>"
    return "，".join(parts) + "<|endofprompt|>"


def parse_server_url(url: str) -> tuple[str, int]:
    parsed = urlparse(url or "")
    host = parsed.hostname or DEFAULT_HOST
    port = parsed.port or DEFAULT_PORT
    return host, int(port)


def resolve_prompt_source(ref_file: str) -> Path:
    """Resolve a user-supplied prompt path, including CosyVoice asset basenames."""
    raw = Path(str(ref_file or "")).expanduser()
    if raw.is_file():
        return raw.resolve()
    name = raw.name
    if name:
        for folder in (
            Path.home() / "CosyVoice" / "asset",
            get_project_root() / "data" / "tts",
            Path("/home/oliver/CosyVoice/asset"),
        ):
            candidate = folder / name
            if candidate.is_file():
                return candidate.resolve()
    raise FileNotFoundError(str(ref_file))


def prepare_prompt_wav(
    source: str | Path,
    *,
    max_seconds: float = PROMPT_MAX_SECONDS,
    sample_rate: int = PROMPT_SAMPLE_RATE,
    cache_dir: Path | None = None,
) -> Path:
    """Convert MP3/WAV/etc. into a short 24 kHz mono WAV CosyVoice can load."""
    import av
    import numpy as np
    import soundfile as sf

    source_path = Path(source).expanduser()
    if not source_path.is_file():
        source_path = resolve_prompt_source(str(source_path))
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
        "CosyVoice prompt prepared source=%s dest=%s seconds=%.2f",
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
    family: str = "cosyvoice2",
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout_seconds: float = 180.0,
) -> str:
    """Start CosyVoice 2/3 if needed and return the HTTP base URL."""
    global _server_proc, _loaded_model
    resolved = resolve_model_dir(model_dir, family=family)
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
