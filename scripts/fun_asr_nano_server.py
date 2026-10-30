# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Owned Fun-ASR-Nano-2512 recognition service. Run with the Fun-ASR-Nano venv.

The model's Qwen3 decoder needs ``transformers>=4.51`` while Nova's main venv
keeps the MuseTalk-compatible release, so recognition runs in its own process
(``scripts/setup-fun-asr-nano.sh``). ``src/asr/fun_asr_nano_service.py`` starts
it only when FunASR is the selected engine.

The model class ships inside the pinned ``funasr`` package and loads with
``trust_remote_code=False``; weights come from ``scripts/fun_asr_nano_weights.py``.
Output is Simplified Chinese, converted with OpenCC ``s2twp`` unless the caller
asks for ``script=simplified``.

Routes (loopback only):
- ``GET /health``: model folder, requested and resolved device.
- ``POST /recognize?language=auto|zh|en&script=traditional-tw|simplified``:
  body is 16 kHz mono PCM16 little-endian audio; returns ``{"text", "language"}``.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_DIR = PROJECT_ROOT / "models" / "funasr" / "Fun-ASR-Nano-2512"
DEFAULT_PORT = 50010
FAMILY = "fun-asr-nano"
SAMPLE_RATE = 16000
MAX_AUDIO_SECONDS = 60
MAX_BODY_BYTES = SAMPLE_RATE * 2 * MAX_AUDIO_SECONDS
DEVICES = ("auto", "cpu", "cuda")
OUTPUT_SCRIPTS = ("traditional-tw", "simplified")
# Fun-ASR-Nano's prompt names the target language; "auto" leaves it out and the
# model recognizes Chinese, English and mixed speech as spoken.
LANGUAGE_HINTS = {"auto": None, "zh": "中文", "en": "英文"}
_HAN = re.compile(r"[㐀-鿿豈-﫿]")
_LATIN = re.compile(r"[A-Za-z]")

logger = logging.getLogger("fun_asr_nano_server")


class RequestError(ValueError):
    """A client error answered with HTTP 400."""


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def text_language(text: str) -> str:
    """``zh`` when the text holds Chinese characters, ``en`` for Latin-only text."""
    if _HAN.search(text):
        return "zh"
    return "en" if _LATIN.search(text) else ""


def pcm16_waveform(body: bytes) -> np.ndarray:
    if not body:
        raise RequestError("沒有音訊")
    if len(body) % 2:
        raise RequestError("音訊須為 16-bit PCM")
    return np.frombuffer(body, dtype="<i2").astype(np.float32) / 32768.0


class Recognizer:
    """Serializes inference on one loaded model and converts its output script."""

    def __init__(self, model, *, model_dir: str, device: str, requested_device: str,
                 converter: Callable[[str], str], waveform: Callable[[np.ndarray], Any] | None = None):
        self._model = model
        self._converter = converter
        self._waveform = waveform or (lambda samples: samples)
        self._lock = threading.Lock()
        self.model_dir = model_dir
        self.device = device
        self.requested_device = requested_device

    def health(self) -> dict:
        return {
            "status": "ok",
            "family": FAMILY,
            "model_dir": self.model_dir,
            "device": self.device,
            "requested_device": self.requested_device,
            "sample_rate": SAMPLE_RATE,
        }

    def recognize(self, body: bytes, *, language: str = "auto", script: str = "traditional-tw") -> dict:
        if language not in LANGUAGE_HINTS:
            raise RequestError(f"不支援的辨識語言: {language}")
        if script not in OUTPUT_SCRIPTS:
            raise RequestError(f"不支援的輸出文字: {script}")
        samples = pcm16_waveform(body)
        with self._lock:
            result = self._model.generate(
                input=[self._waveform(samples)], cache={}, batch_size=1,
                language=LANGUAGE_HINTS[language], itn=True,
            )
            text = str((result[0] if result else {}).get("text", "")).strip()
            if script == "traditional-tw":
                text = self._converter(text)
        return {"text": text, "language": text_language(text)}


def make_handler(recognizer: Recognizer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "FunASRNano"

        def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
            logger.debug("%s " + format, self.address_string(), *args)

        def _reply(self, status: int, payload: dict) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802 - stdlib name
            if urlsplit(self.path).path != "/health":
                self._reply(404, {"error": "not found"})
                return
            self._reply(200, recognizer.health())

        def do_POST(self) -> None:  # noqa: N802 - stdlib name
            url = urlsplit(self.path)
            if url.path != "/recognize":
                self._reply(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY_BYTES:
                self.close_connection = True
                self._reply(413, {"error": f"音訊須在 {MAX_AUDIO_SECONDS} 秒內"})
                return
            query = parse_qs(url.query)
            body = self.rfile.read(length)
            try:
                payload = recognizer.recognize(
                    body,
                    language=query.get("language", ["auto"])[0],
                    script=query.get("script", ["traditional-tw"])[0],
                )
            except RequestError as exc:
                self._reply(400, {"error": str(exc)})
                return
            except Exception:
                logger.exception("recognition failed")
                self._reply(500, {"error": "辨識失敗"})
                return
            self._reply(200, payload)

    return Handler


def resolve_device(requested: str) -> str:
    import torch

    if requested == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise SystemExit("Fun-ASR-Nano 設定要求 CUDA，但目前沒有可用的 CUDA")
    return requested


def load_recognizer(model_dir: Path, requested_device: str) -> Recognizer:
    import torch
    from funasr import AutoModel
    from opencc import OpenCC

    device = resolve_device(requested_device)
    model = AutoModel(model=str(model_dir), device=device, disable_update=True,
                      trust_remote_code=False)
    converter = OpenCC("s2twp").convert
    return Recognizer(model, model_dir=str(model_dir), device=device,
                      requested_device=requested_device, converter=converter,
                      waveform=torch.from_numpy)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fun-ASR-Nano-2512 loopback recognition service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--model_dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--device", default="auto", choices=DEVICES)
    args = parser.parse_args(argv)
    if not is_loopback(args.host):
        parser.error(f"--host 只接受本機位址（loopback），收到 {args.host}")
    args.model_dir = args.model_dir.expanduser().resolve()
    if not (args.model_dir / "model.pt").is_file():
        parser.error(f"找不到 Fun-ASR-Nano 權重：{args.model_dir}（執行 scripts/fun_asr_nano_weights.py）")
    return args


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stderr)
    args = parse_args(argv)
    recognizer = load_recognizer(args.model_dir, args.device)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(recognizer))
    logger.info("Fun-ASR-Nano ready http://%s:%s model=%s device=%s",
                args.host, args.port, args.model_dir, recognizer.device)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
