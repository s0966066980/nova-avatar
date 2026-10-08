#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Download pinned, architecture-independent resources for the native image."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

import nltk
from huggingface_hub import snapshot_download

MODELS = {
    "InfiniFlow/deepdoc": "9c7aa2c730d7a242d7f04cf6109a6a239aefc717",
    "InfiniFlow/text_concat_xgb_v1.0": "722ed09a54f23f14fe0279ce6b74ce18e1960f54",
}
RESOURCES = {
    "tika-server-standard-3.3.0.jar": "https://repo.maven.apache.org/maven2/org/apache/tika/tika-server-standard/3.3.0/tika-server-standard-3.3.0.jar",
    "tika-server-standard-3.3.0.jar.md5": "https://repo.maven.apache.org/maven2/org/apache/tika/tika-server-standard/3.3.0/tika-server-standard-3.3.0.jar.md5",
    "cl100k_base.tiktoken": "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken",
    "libssl1.1_1.1.1f-1ubuntu2_arm64.deb": "https://ports.ubuntu.com/pool/main/o/openssl/libssl1.1_1.1.1f-1ubuntu2_arm64.deb",
}


def prepare(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name, url in RESOURCES.items():
        target = destination / name
        if not target.exists():
            print(f"Downloading {name}", flush=True)
            temporary = target.with_suffix(target.suffix + ".part")
            request = urllib.request.Request(url, headers={"User-Agent": "Nova-Avatar-RAGFlow-Build"})
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
            temporary.replace(target)
    jar = destination / "tika-server-standard-3.3.0.jar"
    expected = (destination / (jar.name + ".md5")).read_text().strip().split()[0]
    if hashlib.md5(jar.read_bytes()).hexdigest() != expected:
        raise RuntimeError("Tika JAR checksum mismatch")
    # NLTK requires a private directory, including its ancestors. A shared
    # checkout can be group writable; download in the user's private home first.
    with tempfile.TemporaryDirectory(prefix=".nova-ragflow-nltk-", dir=Path.home()) as private:
        for package in ("omw-1.4", "wordnet", "punkt", "punkt_tab"):
            if not nltk.download(package, download_dir=private, quiet=True):
                raise RuntimeError(f"NLTK download failed: {package}")
        shutil.copytree(private, destination / "nltk_data", dirs_exist_ok=True)
    for repository, revision in MODELS.items():
        print(f"Downloading {repository} at {revision}", flush=True)
        snapshot = Path(snapshot_download(
            repo_id=repository, revision=revision,
            local_dir=destination / "models" / repository,
            ignore_patterns=["*.git*"],
        ))
        target = destination / "deepdoc"
        target.mkdir(exist_ok=True)
        for source in snapshot.iterdir():
            if source.is_file() and not source.name.startswith("."):
                shutil.copy2(source, target / source.name)
    hashes = {
        str(path.relative_to(destination)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(destination.rglob("*"))
        if path.is_file() and ".cache" not in path.parts and path.name != "manifest.json"
    }
    (destination / "manifest.json").write_text(json.dumps({
        "model_revisions": MODELS, "sha256": hashes,
    }, indent=2) + "\n")
    print(f"ARM64 build resources ready: {len(hashes)} files", flush=True)


if __name__ == "__main__":
    prepare(Path(sys.argv[1]).resolve())
