# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Download and verify the Matcha-TTS base checkpoint for fine-tuning.

``pytorch_model_sherpa.bin`` of ModelScope ``dengcunqin/matcha_tts_zh_en_20251010``
is fetched at a pinned commit and checked against its SHA-256; a missing or
altered file fails the run. Standard library only, so the training venv and the
main project venv can both run it.

Licence: the model page's licence field reads ``Apache License 2.0`` (recorded
2026-11-24); the page does not describe the training data, and the weights are a
fine-tune of ModelScope ``dengcunqin/matcha_tts_zh_en``. The field does not
settle the status of the data, so the project labels every fine-tune of this
base ``Research / Non-commercial`` or stricter (matcha-training spec, decision 3).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.request
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]

REPO = "dengcunqin/matcha_tts_zh_en_20251010"
REVISION = "839c6c33693e1ac54a17a6c4d24ef44d96904674"
FILE_NAME = "pytorch_model_sherpa.bin"
SIZE = 74490446
SHA256 = "a7b0458c146cb1712824a355de27f3969e074b80d02787c9e852fec7006a38ab"
LICENSE_FIELD = "Apache License 2.0"
URL = f"https://www.modelscope.cn/api/v1/models/{REPO}/repo?Revision={REVISION}&FilePath={FILE_NAME}"
PROVENANCE_NAME = "SOURCE.txt"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(url: str, destination: Path) -> None:
    """Stream ``url`` into ``destination`` (https only)."""
    if not url.startswith("https://"):
        raise ValueError(f"refusing a non-https download URL: {url}")
    with urllib.request.urlopen(url, timeout=60) as response, destination.open("wb") as out:  # noqa: S310
        while chunk := response.read(1 << 20):
            out.write(chunk)


def verify(directory: Path) -> str | None:
    """Return the problem with the checkpoint in ``directory``, or ``None`` if it is intact."""
    path = directory / FILE_NAME
    if not path.is_file():
        return f"{path} (missing)"
    if sha256_of(path) != SHA256:
        return f"{path} (sha256 mismatch)"
    return None


def ensure(directory: Path, download: Callable[[str, Path], None] = fetch) -> Path:
    """Make ``directory`` hold the verified checkpoint, downloading only when absent.

    An existing file that fails verification is never replaced silently: it is
    either damaged or not what we pinned, and the operator should look.
    """
    path = directory / FILE_NAME
    directory.mkdir(parents=True, exist_ok=True)
    if path.exists():
        problem = verify(directory)
        if problem:
            raise SystemExit(f"Matcha base checkpoint failed verification: {problem}\nRemove it to download again.")
    else:
        partial = path.with_name(path.name + ".part")
        try:
            download(URL, partial)
            actual = sha256_of(partial)
            if actual != SHA256:
                raise SystemExit(f"Downloaded {FILE_NAME} has sha256 {actual}, expected {SHA256}; discarded.")
            os.replace(partial, path)
        finally:
            partial.unlink(missing_ok=True)
    (directory / PROVENANCE_NAME).write_text(
        f"source: https://www.modelscope.cn/models/{REPO}\n"
        f"revision: {REVISION}\n"
        f"file: {FILE_NAME} ({SIZE} bytes)\n"
        f"sha256: {SHA256}\n"
        f"modelscope licence field: {LICENSE_FIELD}\n"
        "training data: not stated; fine-tunes are labelled Research / Non-commercial or stricter\n",
        encoding="utf-8",
    )
    return path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Download/check the Matcha-TTS base checkpoint")
    parser.add_argument("--check", action="store_true", help="Check an existing file without downloading")
    parser.add_argument("--dir", type=Path, default=ROOT / ".local/matcha-base", help="Target directory")
    args = parser.parse_args(argv)
    if args.check:
        problem = verify(args.dir)
        if problem:
            raise SystemExit(f"Matcha base checkpoint failed verification: {problem}")
    else:
        ensure(args.dir)
    print(f"Matcha base checkpoint verified (pinned revision, sha256): {args.dir / FILE_NAME}", file=sys.stderr)


if __name__ == "__main__":
    main()
