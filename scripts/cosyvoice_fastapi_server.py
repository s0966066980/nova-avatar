# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Owned BreezyVoice FastAPI process. Run with the CosyVoice conda interpreter.

BreezyVoice is a CosyVoice-v1 model loaded through the upstream CosyVoice code
(``~/CosyVoice``). The model folder must hold BreezyVoice's ``word_utils.py``;
text goes through its 注音 frontend and each fragment is synthesized whole
(non-streaming) with zero-shot voice cloning.
"""
from __future__ import annotations

import argparse
import contextlib
import os
import sys
import tempfile

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_HINTS = [
    os.path.expanduser("~/CosyVoice"),
    "/home/oliver/CosyVoice",
]


def _prepare_cosyvoice_path(model_dir: str) -> str:
    model_dir = os.path.abspath(os.path.expanduser(model_dir))
    root = os.path.dirname(os.path.dirname(model_dir.rstrip(os.sep)))
    if os.path.basename(root) != "CosyVoice":
        for hint in PROJECT_HINTS:
            if os.path.isdir(hint):
                root = hint
                break
    sys.path.insert(0, root)
    sys.path.insert(0, os.path.join(root, "third_party", "Matcha-TTS"))
    if ROOT_DIR not in sys.path:
        sys.path.append(ROOT_DIR)  # breezyvoice_frontend, named by its YAML overrides
    os.chdir(root)
    return model_dir


def load_model(model_dir: str):
    """BreezyVoice with its YAML overrides; any other model folder is refused."""
    from breezyvoice_frontend import is_breezyvoice_dir, load_breezyvoice_model

    if not is_breezyvoice_dir(model_dir):
        raise SystemExit(f"不是 BreezyVoice 模型資料夾（缺 word_utils.py）：{model_dir}")
    return load_breezyvoice_model(model_dir)


def _pcm16_chunks(model_output):
    for item in model_output:
        speech = item["tts_speech"].numpy().reshape(-1)
        yield (speech * (2 ** 15)).astype(np.int16).tobytes()


MAX_PROMPT_SECONDS = 8.0


def _save_upload(prompt_wav: UploadFile) -> str:
    suffix = os.path.splitext(prompt_wav.filename or "prompt.wav")[1] or ".wav"
    handle, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(handle, "wb") as output:
        output.write(prompt_wav.file.read())
    return path


def _remove_temporaries(*paths: str | None) -> None:
    for path in paths:
        if path:
            with contextlib.suppress(FileNotFoundError):
                os.remove(path)


def clip_prompt_wav(path: str, *, max_seconds: float = MAX_PROMPT_SECONDS) -> str:
    """Decode MP3/WAV, drop leading silence, keep <=8s mono."""
    import torch
    import torchaudio

    try:
        speech, sample_rate = torchaudio.load(path)
    except Exception:
        speech, sample_rate = torchaudio.load(path, backend="soundfile")
    if speech.numel() == 0:
        raise ValueError("參考音訊是空的")
    speech = speech.mean(dim=0, keepdim=True)
    frame = max(1, int(sample_rate * 0.02))
    squeezed = speech.squeeze(0)
    usable = squeezed[: squeezed.numel() - (squeezed.numel() % frame)]
    max_samples = int(max(0.25, float(max_seconds)) * sample_rate)
    if usable.numel():
        energy = usable.view(-1, frame).abs().mean(dim=1)
        active = torch.nonzero(energy > 0.02, as_tuple=False).flatten()
        if active.numel():
            start = max(0, int(active[0].item() * frame) - int(0.12 * sample_rate))
            speech = speech[:, start : start + max_samples]
        elif speech.shape[1] > max_samples:
            speech = speech[:, :max_samples]
    elif speech.shape[1] > max_samples:
        speech = speech[:, :max_samples]
    handle, clipped = tempfile.mkstemp(suffix=".wav")
    os.close(handle)
    torchaudio.save(clipped, speech, sample_rate)
    return clipped


def create_app(cosyvoice, frontend):
    """``frontend`` (BreezyVoice) rewrites text; synthesis does not stream."""
    app = FastAPI()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        return JSONResponse(
            {
                "status": "ok",
                "sample_rate": int(cosyvoice.sample_rate),
                "prompt_clip": True,
                "prompt_prep": 3,
                "max_prompt_seconds": MAX_PROMPT_SECONDS,
                "model_dir": str(getattr(cosyvoice, "model_dir", "") or ""),
                "family": "breezyvoice",
                "streaming": False,
            }
        )

    @app.post("/inference_zero_shot")
    async def inference_zero_shot(
        tts_text: str = Form(),
        prompt_text: str = Form(""),
        prompt_wav: UploadFile = File(),
    ):
        uploaded = _save_upload(prompt_wav)
        clipped = None
        iterator = None
        first = None
        try:
            clipped = clip_prompt_wav(uploaded)
            iterator = iter(
                cosyvoice.inference_zero_shot(
                    frontend.prepare(tts_text),
                    frontend.prepare(prompt_text or ""),
                    clipped,
                    stream=False,
                    text_frontend=False,
                )
            )
            first = next(iterator, None)
        except Exception as exc:
            _remove_temporaries(uploaded, clipped)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        def generate():
            try:
                if first is not None:
                    yield from _pcm16_chunks([first])
                if iterator is not None:
                    yield from _pcm16_chunks(iterator)
            finally:
                _remove_temporaries(uploaded, clipped)

        return StreamingResponse(generate(), media_type="application/octet-stream")

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=50000)
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument(
        "--model_dir",
        type=str,
        default=os.path.join(os.path.dirname(ROOT_DIR), "models", "BreezyVoice"),
    )
    args = parser.parse_args()
    model_dir = _prepare_cosyvoice_path(args.model_dir)
    cosyvoice = load_model(model_dir)
    from breezyvoice_frontend import BreezyVoiceFrontend

    uvicorn.run(create_app(cosyvoice, BreezyVoiceFrontend(model_dir)), host=args.host, port=int(args.port))


if __name__ == "__main__":
    main()
