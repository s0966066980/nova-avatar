# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Download and verify BreezyVoice weights and its g2pW frontend at pinned revisions.

Every file comes from a fixed commit and is checked against its SHA-256; a
missing or altered file fails the run. The g2pW archive is unpacked only after
its checksum passes. Set ``HF_ENDPOINT`` for a mirror: the checksums still apply.

Layout under ``models/BreezyVoice`` (the folder the ``breezyvoice`` engine finds):
the CosyVoice-v1-style weights, ``word_utils.py`` (BreezyVoice's character
frequency and reading tables), ``g2pw/G2PWModel`` and the
``g2pw/bert-base-chinese`` tokenizer files.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Iterable, NamedTuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.musetalk_weights import WeightSource, _sha256, verify  # noqa: E402

MODEL_DIR = "models/BreezyVoice"
G2PW_ARCHIVE = f"{MODEL_DIR}/g2pw/G2PWModel-v2-onnx.zip"
G2PW_MODEL_DIR = f"{MODEL_DIR}/g2pw/G2PWModel"
G2PW_TOKENIZER_DIR = f"{MODEL_DIR}/g2pw/bert-base-chinese"

MODELS: tuple[WeightSource, ...] = (
    # MediaTek Research, Apache-2.0. flow.encoder / flow.decoder.estimator
    # exports are only needed for JIT / TensorRT and are not fetched.
    WeightSource("MediaTek-Research/BreezyVoice", "e33b502e0ac21c16b0ee0d00df66ac3fa737393d", MODEL_DIR, {
        "cosyvoice.yaml": "5bcbc8cd884a89e921eee20b6c478393b942fe5f007d05846e992be54842b43d",
        "llm.pt": "310c74da4315729c6069c0d0efdfb5bc9b433dc75c890f6ebaf0d18373bda52f",
        "flow.pt": "fd80b089444a95e52956c57cdf177d7f6017a5af13b8a697717628a1d2be6b55",
        "hift.pt": "91e679b6ca1eff71187ffb4f3ab0444935594cdcc20a9bd12afad111ef8d6012",
        "campplus.onnx": "a6ac6a63997761ae2997373e2ee1c47040854b4b759ea41ec48e4e42df0f4d73",
        "speech_tokenizer_v1.onnx": "23b5a723ed9143aebfd9ffda14ac4c21231f31c35ef837b6a13bb9e5488abb1e",
        "spk2info.pt": "652d571b2efec1be6dc14345c2bae52eb41affe4b5d3fa4174548e059bd633b4",
    }),
    # g2pW (Yi-Chang Chen), Apache-2.0; the archive the g2pw package used to
    # fetch from storage.googleapis.com, now hosted by its author.
    WeightSource("YC-Chen/g2pW", "fb4784f7dce8466a53dd4f3552f5a4c5b657b90c", f"{MODEL_DIR}/g2pw", {
        "G2PWModel-v2-onnx.zip": "699f3c1fd7fb0e2c2d49ed2486826fd5bff233fee7759350a91c3b49aedc4ed2",
    }),
    # Tokenizer g2pW was trained with, Apache-2.0. Weights are not needed.
    WeightSource("google-bert/bert-base-chinese", "8f23c25b06e129b6c986331a13d8d025a92cf0ea", G2PW_TOKENIZER_DIR, {
        "vocab.txt": "45bbac6b341c319adc98a532532882e91a9cefc0329aa57bac9ae761c27b291c",
        "tokenizer_config.json": "0f6d13e6f4da6f9e24f22ada6bc3be571123d858d7c0c05a8a7cd55a9c23c2e8",
        "config.json": "88af762cfb15fa9ce183c84dcbfdc9d635196ba635dfe81f265fdd21d67f4c4c",
    }),
)


class UrlFile(NamedTuple):
    url: str
    path: str
    sha256: str


# BreezyVoice's reading tables live only in its GitHub repo (Apache-2.0).
URL_FILES: tuple[UrlFile, ...] = (
    UrlFile(
        "https://raw.githubusercontent.com/mtkresearch/BreezyVoice/"
        "d592c9d3e8927a0f53f68616387060dcd32a05ea/utils/word_utils.py",
        f"{MODEL_DIR}/word_utils.py",
        "d1e315014d6c6596c4b1a596cd856574359317a944ff167d1a52aa74d03d8225",
    ),
)


def _fetch_url(url: str, destination: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as response, destination.open("wb") as output:  # noqa: S310
        shutil.copyfileobj(response, output)


def download(root: Path = ROOT, models: Iterable[WeightSource] = MODELS,
             url_files: Iterable[UrlFile] = URL_FILES,
             snapshot: Callable[..., object] | None = None,
             fetch: Callable[[str, Path], None] = _fetch_url) -> None:
    if snapshot is None:
        from huggingface_hub import snapshot_download as snapshot
    for source in models:
        snapshot(source.repo, revision=source.revision, local_dir=str(root / source.local_dir),
                 allow_patterns=sorted(source.files))
    for item in url_files:
        target = root / item.path
        if target.is_file() and _sha256(target) == item.sha256:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(dir=target.parent, suffix=".part")
        os.close(handle)
        staged = Path(name)
        try:
            fetch(item.url, staged)
            if _sha256(staged) != item.sha256:
                raise SystemExit(f"{item.path} (sha256 mismatch from {item.url})")
            staged.replace(target)
        finally:
            staged.unlink(missing_ok=True)


def verify_all(root: Path = ROOT, models: Iterable[WeightSource] = MODELS,
               url_files: Iterable[UrlFile] = URL_FILES) -> list[str]:
    """Return one problem per missing or altered file; empty means verified."""
    problems = verify(root, models)
    for item in url_files:
        path = root / item.path
        if not path.is_file():
            problems.append(f"{item.path} (missing)")
        elif _sha256(path) != item.sha256:
            problems.append(f"{item.path} (sha256 mismatch)")
    return problems


def unpack_g2pw(root: Path = ROOT) -> Path:
    """Extract the verified g2pW archive once; refuses entries outside its folder."""
    archive = root / G2PW_ARCHIVE
    target = root / G2PW_MODEL_DIR
    if (target / "g2pw.onnx").is_file():
        return target
    parent = archive.parent.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            resolved = (parent / name).resolve()
            if not resolved.is_relative_to(target.resolve()):
                raise SystemExit(f"{G2PW_ARCHIVE} has an unexpected entry: {name}")
        bundle.extractall(parent)
    if not (target / "g2pw.onnx").is_file():
        raise SystemExit(f"{G2PW_ARCHIVE} did not contain G2PWModel/g2pw.onnx")
    return target


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Download/check BreezyVoice weights at pinned revisions")
    parser.add_argument("--check", action="store_true", help="Check existing files without downloading")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not args.check:
        download(args.root)
    problems = verify_all(args.root)
    if problems:
        raise SystemExit("BreezyVoice weights failed verification:\n" + "\n".join(problems))
    if not args.check:
        unpack_g2pw(args.root)
    print("BreezyVoice and g2pW weights verified (pinned revisions, sha256).")


if __name__ == "__main__":
    main()
