#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Qwen3-TTS evaluation server for the TTS bake-off (issue 10).

Serves Qwen3-TTS through ``faster-qwen3-tts`` (MIT; CUDA graphs, streaming)
behind the same contract as ``scripts/cosyvoice_fastapi_server.py``:
``GET /health`` reports ``sample_rate``; ``POST /inference_zero_shot`` takes
``tts_text``, ``prompt_text`` and ``prompt_wav`` (plus ``language``:
Chinese, English or Auto) and streams raw PCM16. It binds loopback only and
takes its model from the command line, never from a request.

Run it in its own environment, not the project venv (faster-qwen3-tts needs
torch >= 2.5.1 and transformers 5, and replaces ``qwen-tts``)::

    /home/oliver/.venvs/faster-qwen3-tts/bin/python scripts/qwen3_tts_server.py \
        --model Qwen/Qwen3-TTS-12Hz-0.6B-Base --port 50010

The reference recording is used as uploaded (no clipping): keep it under about
8 seconds and pass its exact transcript as ``prompt_text``.
"""
# No ``from __future__ import annotations``: FastAPI must resolve the handler
# annotations, and fastapi is imported inside create_app (absent from the project venv).
import argparse
import hashlib
import ipaddress
import tempfile
import threading
from pathlib import Path
from typing import Any, Iterator

import numpy as np

# The Qwen3-TTS 12 Hz speech tokenizer decodes at 24 kHz; the model's own value wins.
DEFAULT_SAMPLE_RATE = 24000
LANGUAGES = ("Chinese", "English", "Auto")


def require_loopback(host: str) -> None:
    """The server has no authentication, so it may only listen on loopback (ADR 0021)."""
    if host == "localhost":
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise ValueError(f"refusing to listen on non-loopback host {host!r}")


def _pcm16(audio: Any) -> bytes:
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    return (np.clip(samples, -1.0, 1.0) * 32767.0).round().astype(np.int16).tobytes()


class Qwen3Synthesizer:
    """Serializes generation on one model and caches the cloned voice per recording."""

    def __init__(self, model: Any, *, prompt_dir: Path, chunk_size: int = 4, speaker: str | None = None):
        self.model = model
        self.prompt_dir = Path(prompt_dir)
        self.chunk_size = chunk_size
        self.speaker = speaker
        self.sample_rate = int(getattr(model, "sample_rate", None) or DEFAULT_SAMPLE_RATE)
        self._lock = threading.Lock()

    @property
    def mode(self) -> str:
        return "custom_voice" if self.speaker else "voice_clone"

    def _prompt_path(self, data: bytes) -> Path:
        # faster-qwen3-tts caches the voice prompt by path; one path per recording keeps it warm.
        path = self.prompt_dir / f"{hashlib.sha256(data).hexdigest()}.wav"
        if not path.is_file():
            path.write_bytes(data)
        return path

    def stream(self, text: str, prompt_text: str, prompt_wav: bytes, language: str) -> Iterator[bytes]:
        if language not in LANGUAGES:
            raise ValueError(f"unsupported language {language!r}; use one of {', '.join(LANGUAGES)}")
        with self._lock:
            if self.speaker:
                chunks = self.model.generate_custom_voice_streaming(
                    text=text, speaker=self.speaker, language=language, chunk_size=self.chunk_size)
            else:
                chunks = self.model.generate_voice_clone_streaming(
                    text=text, language=language, ref_audio=str(self._prompt_path(prompt_wav)),
                    ref_text=prompt_text, chunk_size=self.chunk_size)
            for audio, sample_rate, _timing in chunks:
                if int(sample_rate) != self.sample_rate:
                    raise RuntimeError(f"model produced {sample_rate} Hz, server reports {self.sample_rate} Hz")
                yield _pcm16(audio)


def create_app(synthesizer: Qwen3Synthesizer, *, model_name: str):
    from fastapi import FastAPI, File, Form, HTTPException, UploadFile
    from fastapi.responses import JSONResponse, StreamingResponse

    app = FastAPI()

    @app.get("/health")
    def health():
        return JSONResponse({
            "status": "ok", "sample_rate": synthesizer.sample_rate, "family": "qwen3-tts", "model": model_name,
            "mode": synthesizer.mode, "streaming": True, "chunk_size": synthesizer.chunk_size,
        })

    # Plain ``def`` handlers run in FastAPI's worker threads, so generation
    # never blocks the event loop (CODING_STANDARDS rule 3).
    @app.post("/inference_zero_shot")
    def inference_zero_shot(
        tts_text: str = Form(),
        prompt_text: str = Form(""),
        language: str = Form("Auto"),
        prompt_wav: UploadFile = File(),
    ):
        chunks = synthesizer.stream(tts_text, prompt_text, prompt_wav.file.read(), language)
        try:
            first = next(chunks, b"")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc

        def body():
            yield first
            yield from chunks

        return StreamingResponse(body(), media_type="application/octet-stream")

    return app


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
                        help="HF id or local folder; a CustomVoice model also needs --speaker")
    parser.add_argument("--speaker", help="CustomVoice speaker (ignores the uploaded reference)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=50010)
    parser.add_argument("--chunk-size", type=int, default=4, help="codec steps per streamed chunk (12 per second)")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", default="bfloat16", choices=("bfloat16", "float16", "float32"))
    args = parser.parse_args(argv)
    require_loopback(args.host)

    import torch
    import uvicorn
    from faster_qwen3_tts import FasterQwen3TTS

    model = FasterQwen3TTS.from_pretrained(args.model, device=args.device, dtype=getattr(torch, args.dtype))
    model.warmup(prefill_len=100)  # capture CUDA graphs before serving, as a deployment would
    with tempfile.TemporaryDirectory(prefix="qwen3-tts-prompts-") as prompt_dir:
        synthesizer = Qwen3Synthesizer(model, prompt_dir=Path(prompt_dir), chunk_size=args.chunk_size,
                                       speaker=args.speaker)
        uvicorn.run(create_app(synthesizer, model_name=args.model), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
