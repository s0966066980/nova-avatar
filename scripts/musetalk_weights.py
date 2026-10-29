# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Download and verify MuseTalk weights at pinned Hub commits.

Every file is fetched from a fixed commit and checked against its SHA-256;
a missing or altered file fails the run. Set ``HF_ENDPOINT`` for a mirror:
the checksums still apply, so a mirror cannot substitute other weights.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Callable, Iterable, NamedTuple

ROOT = Path(__file__).resolve().parents[1]


class WeightSource(NamedTuple):
    repo: str
    revision: str
    local_dir: str
    files: dict[str, str]


MODELS: tuple[WeightSource, ...] = (
    WeightSource("TMElyralab/MuseTalk", "2bcb936e2fddb4d86db4c62fd45b387d0c061571", "models/musetalk", {
        "musetalkV15/unet.pth": "7ebf6c98c181e20838e4c0054e96e944ac60d5d692cc01db42839fe11b787007",
        "musetalkV15/musetalk.json": "5b6923aee04d71692e0e9846c471e0a4ea07a4f686d39545e472bd4ba17e1b47",
    }),
    WeightSource("stabilityai/sd-vae-ft-mse", "31f26fdeee1355a5c34592e401dd41e45d25a493", "models/sd-vae", {
        "config.json": "92d3dfb746fca211a2c9e019e285f8597412211728dce3c5bcf4eda0f2d62e7e",
        "diffusion_pytorch_model.bin": "1b4889b6b1d4ce7ae320a02dedaeff1780ad77d415ea0d744b476155c6377ddc",
    }),
    WeightSource("openai/whisper-tiny", "169d4a4341b33bc18d8881c4b69c2e104e1cc0af", "models/musetalk/whisper", {
        "config.json": "ffdccec4f3211f4c63310f2b7098f309fe70f3952cedc5e4d11e43f5b2379b98",
        "pytorch_model.bin": "9607f98a2b22d9e229ae43c52ecea79dcede9e0c5cfae67e8da6eda86d8aac1d",
        "preprocessor_config.json": "9b5cd03a36fbb8a627c64d98a5b5b126ead95a77720723944487311f0110b666",
    }),
    WeightSource("yzd-v/DWPose", "1a7144101628d69ee7a3768d1ee3a094070dc388", "models/musetalk/dwpose", {
        "dw-ll_ucoco_384.pth": "0d9408b13cd863c4e95a149dd31232f88f2a12aa6cf8964ed74d7d97748c7a07",
    }),
    WeightSource("ManyOtherFunctions/face-parse-bisent", "0073b233a5a3c4b1377d4dbf49245017938a72b5",
                 "models/face-parse-bisent", {
        "79999_iter.pth": "468e13ca13a9b43cc0881a9f99083a430e9c0a38abd935431d1c28ee94b26567",
        "resnet18-5c106cde.pth": "5c106cde386e87d4033832f2996f5493238eda96ccf559d1d62760c4de0613f8",
    }),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(root: Path = ROOT, models: Iterable[WeightSource] = MODELS,
             snapshot: Callable[..., object] | None = None) -> None:
    if snapshot is None:
        from huggingface_hub import snapshot_download as snapshot
    for source in models:
        snapshot(source.repo, revision=source.revision, local_dir=str(root / source.local_dir),
                 allow_patterns=sorted(source.files))


def verify(root: Path = ROOT, models: Iterable[WeightSource] = MODELS) -> list[str]:
    """Return one problem per missing or altered file; empty means verified."""
    problems = []
    for source in models:
        for name, expected in source.files.items():
            relative = f"{source.local_dir}/{name}"
            path = root / relative
            if not path.is_file():
                problems.append(f"{relative} (missing)")
            elif _sha256(path) != expected:
                problems.append(f"{relative} (sha256 mismatch)")
    return problems


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Download/check MuseTalk weights at pinned revisions")
    parser.add_argument("--check", action="store_true", help="Check existing files without downloading")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not args.check:
        download(args.root, MODELS)
    problems = verify(args.root, MODELS)
    if problems:
        raise SystemExit("MuseTalk weights failed verification:\n" + "\n".join(problems))
    print("MuseTalk inference and avatar-preparation weights verified (pinned revisions, sha256).")


if __name__ == "__main__":
    main()
