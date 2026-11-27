# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""CPU faster-whisper worker for the training job's transcript check.

Started by ``asr.SubprocessTranscriber`` as ``python -m src.tts.training.whisper_worker
--model <size>`` in a child of the application's own interpreter with
``CUDA_VISIBLE_DEVICES=`` set, so it never touches the GPU the training needs.

Protocol, one JSON object per line: it prints ``{"ready": true}`` once the model is
loaded; for every request ``{"path": "<audio file>"}`` on standard input it prints
``{"text": "<recognised text>"}`` or ``{"error": "<reason>"}``. Other output lines
(library log noise) are ignored by the parent. End of input ends the worker.

Language handling follows the speech engine: detect, and when the detected language
is neither Chinese nor English choose the likelier of the two and decode again.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any, TextIO

LANGUAGES = ("zh", "en")
COMPUTE_TYPE = "int8"
LOCAL_MODEL_DIRS = {"small": "whisper-small", "turbo": "whisper-large-v3-turbo"}


def recognise(model: Any, path: str) -> str:
    segments, info = model.transcribe(path, language=None, beam_size=1, vad_filter=False)
    language = getattr(info, "language", None)
    if language not in LANGUAGES:
        scores = dict(getattr(info, "all_language_probs", None) or ())
        language = max(LANGUAGES, key=lambda code: scores.get(code, 0.0))
        segments, _ = model.transcribe(path, language=language, beam_size=1, vad_filter=False)
    return "".join(segment.text for segment in segments).strip()


def serve(model: Any, requests: Iterable[str], out: TextIO) -> None:
    out.write(json.dumps({"ready": True}) + "\n")
    out.flush()
    for raw in requests:
        raw = raw.strip()
        if not raw:
            continue
        try:
            reply: dict[str, Any] = {"text": recognise(model, json.loads(raw)["path"])}
        except Exception as exc:
            reply = {"error": f"{type(exc).__name__}: {exc}"}
        out.write(json.dumps(reply, ensure_ascii=False) + "\n")
        out.flush()


def load_model(size: str, root: Path):
    from faster_whisper import WhisperModel

    local = LOCAL_MODEL_DIRS.get(size)
    path = root / "models" / local if local else None
    source = str(path) if path is not None and (path / "model.bin").is_file() else size
    return WhisperModel(source, device="cpu", compute_type=COMPUTE_TYPE)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[3]
    serve(load_model(args.model, root), sys.stdin, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
