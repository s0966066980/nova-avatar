# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Download pinned official OpenAI assets; convert sequentially on the CPU."""

import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
MODELS = {
    "small": ("openai/whisper-small", "973afd24965f72e36ca33b3055d56a652f456b4d"),
    "large-v3-turbo": ("openai/whisper-large-v3-turbo", "41f01f3fe87f28c78e2fbf8b568835947dd65ed9"),
}
FILES = {
    "README.md", "model.safetensors", "config.json", "generation_config.json",
    "preprocessor_config.json", "tokenizer.json", "tokenizer_config.json",
    "vocab.json", "merges.txt", "normalizer.json", "special_tokens_map.json",
    "added_tokens.json", "LICENSE",
}


def get_json(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest, expected_size=None, expected_sha=None):
    if dest.exists() and (expected_size is None or dest.stat().st_size == expected_size):
        sha = digest(dest)
        if expected_sha is None or sha == expected_sha:
            return sha
    partial = dest.with_name(dest.name + ".partial")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url + ("&" if "?" in url else "?") + f"download=true&benchmark_nonce={time.time_ns()}", headers={"User-Agent": "Nova-Avatar-ASR-source-audit/1.0"})
            done = 0
            next_progress = 128 * 1024 * 1024
            h = hashlib.sha256()
            with urllib.request.urlopen(req, timeout=90) as response, partial.open("wb") as target:
                while chunk := response.read(4 * 1024 * 1024):
                    target.write(chunk)
                    h.update(chunk)
                    done += len(chunk)
                    if done >= next_progress:
                        print(f"DOWNLOAD {dest.parent.parent.name}/{dest.name}: {done / 1e6:.0f} MB", flush=True)
                        next_progress += 128 * 1024 * 1024
            assert expected_size is None or done == expected_size, (dest, done, expected_size)
            assert expected_sha is None or h.hexdigest() == expected_sha, (dest, "SHA256 mismatch")
            partial.replace(dest)
            return h.hexdigest()
        except Exception as exc:
            print(f"DOWNLOAD retry {attempt + 1}: {dest.name}: {type(exc).__name__}: {exc}", flush=True)
            if attempt == 2:
                raise


def download_model(item):
    label, (repo, revision) = item
    target = ROOT / "models" / f"whisper-{label}"
    source = target / "source-openai"
    source.mkdir(parents=True, exist_ok=True)
    metadata_url = f"https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true"
    metadata = get_json(metadata_url)
    assert metadata["sha"] == revision
    (source / "hub-metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    files = []
    print(f"START official download {repo}@{revision}", flush=True)
    ordered = sorted((entry for entry in metadata["siblings"] if entry["rfilename"] in FILES), key=lambda e: e["rfilename"] == "model.safetensors")
    for entry in ordered:
        name = entry["rfilename"]
        url = f"https://huggingface.co/{repo}/resolve/{revision}/{name}"
        sha = download(url, source / name, entry.get("size"), entry.get("lfs", {}).get("sha256"))
        files.append({"name": name, "source_url": url, "size": (source / name).stat().st_size, "sha256": sha, "upstream_lfs_sha256": entry.get("lfs", {}).get("sha256")})
    record = {"model": label, "repo": repo, "revision": revision, "local_model_path": str(target.relative_to(ROOT)), "source_files": files, "model_card_license_metadata": metadata.get("cardData", {}).get("license"), "conversion": None}
    (target / "SOURCE-MANIFEST.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    print(f"DOWNLOADED and verified {label}", flush=True)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--convert-only", action="store_true")
    parser.add_argument("--one-conversion", choices=MODELS)
    args = parser.parse_args()
    if args.one_conversion:
        from ctranslate2.converters import TransformersConverter
        class InstalledTransformersConverter(TransformersConverter):
            def load_model(self, model_class, model_name_or_path, **kwargs):
                # CT2 4.8.2 passes dtype; installed Transformers 4.46 uses
                # torch_dtype. Translate the keyword only, within this process.
                if "dtype" in kwargs:
                    kwargs["torch_dtype"] = kwargs.pop("dtype")
                return super().load_model(model_class, model_name_or_path, **kwargs)
        dest = ROOT / "models" / f"whisper-{args.one_conversion}"
        started = time.perf_counter()
        converted = dest / "ctranslate2-staging"
        InstalledTransformersConverter(str(dest / "source-openai"), copy_files=["tokenizer.json", "preprocessor_config.json"], load_as_float16=True, low_cpu_mem_usage=True).convert(str(converted), quantization="float16", force=False)
        for artifact in converted.iterdir():
            assert not (dest / artifact.name).exists(), artifact.name
            artifact.replace(dest / artifact.name)
        converted.rmdir()
        manifest = json.loads((dest / "SOURCE-MANIFEST.json").read_text())
        import importlib.metadata
        manifest["conversion"] = {"method": "local ctranslate2.converters.TransformersConverter; process-local dtype -> torch_dtype keyword compatibility adapter for Transformers 4.46", "device": "CPU", "quantization": "float16", "seconds": time.perf_counter() - started, "ctranslate2": importlib.metadata.version("ctranslate2"), "transformers": importlib.metadata.version("transformers"), "trained_or_finetuned": False, "files": [{"name": p.name, "size": p.stat().st_size, "sha256": digest(p)} for p in sorted(dest.iterdir()) if p.is_file() and p.name not in {"SOURCE-MANIFEST.json", "LICENSE"}]}
        (dest / "SOURCE-MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        print(f"CONVERTED {args.one_conversion} in {manifest['conversion']['seconds']:.2f}s", flush=True)
        return
    OUT.mkdir(parents=True, exist_ok=True)
    if not args.convert_only:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(download_model, MODELS.items()))
    upstream = get_json("https://api.github.com/repos/openai/whisper/commits/main")
    sha = upstream["sha"]
    license_url = f"https://raw.githubusercontent.com/openai/whisper/{sha}/LICENSE"
    license_path = OUT / "openai-whisper-LICENSE.txt"
    download(license_url, license_path)
    (OUT / "license-source.json").write_text(json.dumps({"repo": "https://github.com/openai/whisper", "revision": sha, "license_url": license_url, "license_sha256": digest(license_path), "license": "MIT", "weight_scope": "OpenAI README license section explicitly covers code and model weights", "small_hub_metadata_note": "The pinned openai/whisper-small card metadata labels apache-2.0, while OpenAI original repo explicitly licenses code and model weights MIT; preserve both statements, do not silently relabel."}, indent=2) + "\n")
    for label in MODELS:
        dest = ROOT / "models" / f"whisper-{label}"
        (dest / "LICENSE").write_text(license_path.read_text())
        if (dest / "model.bin").exists():
            continue
        env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HOME=str(OUT / "cache" / "huggingface"), PYTHONDONTWRITEBYTECODE="1", OMP_NUM_THREADS="4", OPENBLAS_NUM_THREADS="4")
        subprocess.run([sys.executable, str(Path(__file__).resolve()), "--one-conversion", label], check=True, env=env)
    records = [json.loads((ROOT / "models" / f"whisper-{label}" / "SOURCE-MANIFEST.json").read_text()) for label in MODELS]
    (OUT / "model-manifest.json").write_text(json.dumps({"models": records, "license_source": json.loads((OUT / "license-source.json").read_text())}, ensure_ascii=False, indent=2) + "\n")
    print("ALL model assets prepared", flush=True)


if __name__ == "__main__":
    main()
