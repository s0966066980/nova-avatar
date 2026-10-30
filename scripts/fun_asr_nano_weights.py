# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Download and verify Fun-ASR-Nano-2512 weights at a pinned revision.

Every file comes from a fixed commit and is checked against its SHA-256; a
missing or altered file fails the run. Set ``HF_ENDPOINT`` for a mirror: the
checksums still apply.

The model class ships inside the ``funasr`` package (``funasr.models.fun_asr_nano``),
so no model code is downloaded: the repository has none, and the service
(``scripts/fun_asr_nano_server.py``) loads it with ``trust_remote_code=False``. ``Qwen3-0.6B`` holds only the decoder's
config and tokenizer; its weights are inside ``model.pt``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.musetalk_weights import WeightSource, verify  # noqa: E402

MODEL_DIR = "models/funasr/Fun-ASR-Nano-2512"

MODELS: tuple[WeightSource, ...] = (
    # Tongyi Lab (FunAudioLLM), Apache-2.0.
    WeightSource("FunAudioLLM/Fun-ASR-Nano-2512", "272c57b82523ada6fd87095e955f8e29100979ab", MODEL_DIR, {
        "config.yaml": "daed38ea6484f5650fb32cbd9069b9aa13880acaf2bcb1f0bf4be2712837917c",
        "configuration.json": "b64a3a55d35bcbe2cf4d31f2d3ef25a423d3ba2ebff203298c27fa055f3c7612",
        "model.pt": "55ae0d2fee369f0f11cce0795f6927934ad17cf11b278a7e56a51272074160bb",
        "multilingual.tiktoken": "747979631e813193436aabcff7c1c235d37de8097b71c563ec8b63b7a515c718",
        "Qwen3-0.6B/config.json": "660db3b73d788119c04535e48cf9be5f55bc3100841a718637ae695b442f27dd",
        "Qwen3-0.6B/generation_config.json": "2325da0f15bb848e018c5ae071b7943332e9f871d6b60e2ed22ca97d4cb993d2",
        "Qwen3-0.6B/merges.txt": "8831e4f1a044471340f7c0a83d7bd71306a5b867e95fd870f74d0c5308a904d5",
        "Qwen3-0.6B/tokenizer.json": "aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4",
        "Qwen3-0.6B/tokenizer_config.json": "d5d09f07b48c3086c508b30d1c9114bd1189145b74e982a265350c923acd8101",
        "Qwen3-0.6B/vocab.json": "ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910",
    }),
)


def download(root: Path = ROOT, models: Iterable[WeightSource] = MODELS,
             snapshot: Callable[..., object] | None = None) -> None:
    if snapshot is None:
        from huggingface_hub import snapshot_download as snapshot
    for source in models:
        snapshot(source.repo, revision=source.revision, local_dir=str(root / source.local_dir),
                 allow_patterns=sorted(source.files))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Download/check Fun-ASR-Nano-2512 weights at a pinned revision")
    parser.add_argument("--check", action="store_true", help="Check existing files without downloading")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not args.check:
        download(args.root)
    problems = verify(args.root, MODELS)
    if problems:
        raise SystemExit("Fun-ASR-Nano-2512 weights failed verification:\n" + "\n".join(problems))
    print("Fun-ASR-Nano-2512 weights verified (pinned revision, sha256).")


if __name__ == "__main__":
    main()
