#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Connect Nova and its embedding provider without displaying credentials.

An existing working API key is retained. A stale migrated key is backed up,
then replaced using the deployment's private bootstrap administrator password.
This does not reset any account password or delete an existing API token.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / "config/ragflow.env"
BASE_URL = "http://127.0.0.1:9380"


def read_key() -> str:
    if not ENV_FILE.exists():
        return ""
    for line in ENV_FILE.read_text().splitlines():
        match = re.match(r"(?:export\s+)?NOVA_RAGFLOW_API_KEY=(.*)$", line)
        if match:
            values = shlex.split(match[1], comments=True)
            return values[0] if values else ""
    return ""


def works(key: str) -> bool:
    if not key:
        return False
    request = urllib.request.Request(
        BASE_URL + "/api/v1/datasets?page_size=1",
        headers={"Authorization": "Bearer " + key},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response).get("code") == 0
    except (urllib.error.URLError, ValueError):
        return False


def configure_embedding(key: str) -> None:
    def api(method: str, path: str, body: dict | None = None):
        request = urllib.request.Request(
            BASE_URL + "/api/v1" + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.load(response)
        if result.get("code") != 0:
            raise RuntimeError(f"RAGFlow 模型設定失敗：{method} {path}")
        return result.get("data")

    if not any(provider.get("name") == "Ollama" for provider in api("GET", "/providers")):
        api("PUT", "/providers", {"provider_name": "Ollama"})
    instance_name = "nova-arm64"
    instances = api("GET", "/providers/Ollama/instances")
    if not any(instance.get("instance_name") == instance_name for instance in instances):
        api("POST", "/providers/Ollama/instances", {
            "instance_name": instance_name, "api_key": "", "region": "",
            "base_url": "http://host.docker.internal:11435",
            "model_info": [{"model_name": "bge-m3", "model_type": ["embedding"], "max_tokens": 8192}],
        })
    defaults = api("GET", "/models/default")
    if not any(model.get("model_type") == "embedding" for model in defaults["models"]):
        api("PATCH", "/models/default", {
            "model_provider": "Ollama", "model_instance": instance_name,
            "model_name": "bge-m3", "model_type": "embedding",
        })
    print("Ollama / nova-arm64 / BGE-M3 已設定；既有有效的預設模型已保留。")


def prepare() -> None:
    existing_key = read_key()
    if works(existing_key):
        ENV_FILE.chmod(0o600)
        print("Nova 的既有 RAGFlow API 金鑰有效，已沿用。")
        configure_embedding(existing_key)
        return
    # Encrypt the password with this pinned server's own public key, then use
    # the normal authenticated API to issue a token. Only the parent process
    # receives the credential; it is never emitted to the terminal.
    program = r'''
import json, os, urllib.request
from api.utils.crypt import crypt
base = "http://127.0.0.1:9380/api/v1"
def call(path, body, auth=None):
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = auth
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=30) as res:
        payload = json.load(res)
        if payload.get("code") != 0:
            raise RuntimeError("RAGFlow rejected the bootstrap operation")
        return payload, res.headers.get("Authorization")
password = os.environ.get("ADMIN_DEFAULT_PASSWORD") or os.environ.get("DEFAULT_SUPERUSER_PASSWORD")
if not password:
    raise RuntimeError("No private bootstrap password is available")
_, auth = call("/auth/login", {"email": os.environ.get("DEFAULT_SUPERUSER_EMAIL", "admin@ragflow.io"), "password": crypt(password)})
if not auth:
    raise RuntimeError("Administrator login returned no authorization")
payload, _ = call("/system/tokens", {}, auth)
print(json.dumps({"token": payload["data"]["token"]}))
'''
    result = subprocess.run(
        ["docker", "exec", "-i", "nova-ragflow-ragflow-cpu-1", "python", "-"],
        input=program, text=True, capture_output=True,
    )
    if result.returncode:
        raise RuntimeError("管理登入或建立 API 金鑰失敗；現有設定未變更。請在 RAGFlow 管理介面建立金鑰。")
    key = json.loads(result.stdout)["token"]
    if not works(key):
        raise RuntimeError("新 API 金鑰驗證失敗；現有設定未變更。")
    original = ENV_FILE.read_text() if ENV_FILE.exists() else ""
    if original:
        backups = ROOT / ".local/ragflow/backups"
        backups.mkdir(parents=True, exist_ok=True, mode=0o700)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_fd = os.open(backups / f"nova-connection-{stamp}.env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(backup_fd, "w") as output:
            output.write(original)
    lines = [line for line in original.splitlines() if not re.match(r"(?:export\s+)?NOVA_RAGFLOW_(API_KEY|URL)=", line)]
    content = "\n".join(lines + [f"NOVA_RAGFLOW_URL={BASE_URL}", f"NOVA_RAGFLOW_API_KEY={shlex.quote(key)}", ""])
    fd, name = tempfile.mkstemp(prefix=".ragflow-connection-", dir=ENV_FILE.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, ENV_FILE)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    print("Nova 的 RAGFlow 連線已建立；舊設定已備份，金鑰未輸出。")
    configure_embedding(key)


if __name__ == "__main__":
    prepare()
