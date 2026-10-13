#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Load the dedicated embedding model before an interactive retrieval turn."""
import json
import subprocess
import urllib.request
from pathlib import Path


def warm() -> None:
    gateway = subprocess.check_output([
        "docker", "network", "inspect", "bridge", "--format",
        "{{(index .IPAM.Config 0).Gateway}}",
    ], text=True).strip()
    shared = (Path(__file__).resolve().parents[1] / ".local/ragflow/shared-ollama").exists()
    base = f"http://{gateway}:{11436 if shared else 11435}"
    with urllib.request.urlopen(base + "/api/tags", timeout=10) as response:
        models = json.load(response)["models"]
    if not any(model["name"].split(":")[0] == "bge-m3" for model in models):
        print("BGE-M3 尚未下載，請執行 bash scripts/ragflow.sh pull-model。")
        return
    request = urllib.request.Request(
        base + "/api/embed",
        # Match RAGFlow's OllamaEmbed options. Changing use_mmap between warmup
        # and retrieval makes Ollama reload its runner on the first real request.
        data=json.dumps({
            "model": "bge-m3", "input": ["Nova Avatar embedding warmup"],
            "options": {"use_mmap": True}, "keep_alive": -1,
        }).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.load(response)
    if len(result["embeddings"][0]) != 1024:
        raise RuntimeError("Unexpected BGE-M3 embedding dimensions")
    print("BGE-M3 已預熱，1024 維向量驗證通過。")


if __name__ == "__main__":
    warm()
