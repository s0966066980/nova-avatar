#!/usr/bin/env bash
# Derived from Kedreamix/Linly-Talker-Stream; Apache-2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
# Use the project's pinned huggingface-hub; do not upgrade it with system pip.
# Set HF_ENDPOINT explicitly if a mirror is required.
uv run --no-sync python - "$@" <<'PYTHON'
import argparse
from pathlib import Path
from huggingface_hub import snapshot_download
parser = argparse.ArgumentParser(description="Download/check MuseTalk weights in the project environment")
parser.add_argument("--check", action="store_true", help="Check existing files without downloading")
args = parser.parse_args()
models = [
    ("TMElyralab/MuseTalk", "models/musetalk", ["musetalkV15/*"]),
    ("stabilityai/sd-vae-ft-mse", "models/sd-vae", ["config.json", "diffusion_pytorch_model.bin"]),
    ("openai/whisper-tiny", "models/musetalk/whisper", ["config.json", "pytorch_model.bin", "preprocessor_config.json"]),
    ("yzd-v/DWPose", "models/musetalk/dwpose", ["dw-ll_ucoco_384.pth"]),
    ("ManyOtherFunctions/face-parse-bisent", "models/face-parse-bisent", ["79999_iter.pth", "resnet18-5c106cde.pth"]),
]
if not args.check:
    for repo, directory, patterns in models:
        snapshot_download(repo, local_dir=directory, allow_patterns=patterns)
required = [
    "models/musetalk/musetalkV15/unet.pth",
    "models/musetalk/musetalkV15/musetalk.json",
    "models/sd-vae/config.json",
    "models/sd-vae/diffusion_pytorch_model.bin",
    "models/musetalk/whisper/config.json",
    "models/musetalk/whisper/pytorch_model.bin",
    "models/musetalk/whisper/preprocessor_config.json",
    "models/musetalk/dwpose/dw-ll_ucoco_384.pth",
    "models/face-parse-bisent/79999_iter.pth",
    "models/face-parse-bisent/resnet18-5c106cde.pth",
]
missing = [name for name in required if not Path(name).is_file()
           or Path(name).stat().st_size < (1024 if name.endswith((".bin", ".pth")) else 1)]
if missing:
    raise SystemExit("Missing weights:\n" + "\n".join(missing))
print("MuseTalk inference and avatar-preparation weights verified.")
PYTHON
