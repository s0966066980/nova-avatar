#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Connect Nova and its embedding provider without displaying credentials.

An existing working API key is retained. A stale migrated key is backed up,
then replaced using the deployment's private bootstrap administrator password.
This does not reset any account password or delete an existing API token.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shlex
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / "config/ragflow.env"
BASE_URL = "http://127.0.0.1:9380"
SHARED_OLLAMA = ROOT / ".local/ragflow/shared-ollama"
SHARED_MODEL_URL = "http://host.docker.internal:11436"


def ollama_api(path: str, body: dict | None = None, *, base: str = "http://127.0.0.1:11434"):
    # Every caller passes a fixed http:// base: loopback or the docker gateway.
    request = urllib.request.Request(  # noqa: S310 -- fixed http:// Ollama base
        base + path, data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:  # noqa: S310 -- same request
        return json.load(response)


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
    request = urllib.request.Request(  # noqa: S310 -- fixed loopback BASE_URL
        BASE_URL + "/api/v1/datasets?page_size=1",
        headers={"Authorization": "Bearer " + key},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 -- same request
            return json.load(response).get("code") == 0
    except (urllib.error.URLError, ValueError):
        return False


def model_api(key: str, method: str, path: str, body: dict | None = None):
    request = urllib.request.Request(  # noqa: S310 -- fixed loopback BASE_URL
        BASE_URL + "/api/v1" + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 -- same request
        result = json.load(response)
    if result.get("code") != 0:
        raise RuntimeError(f"RAGFlow 模型設定失敗：{method} {path}")
    return result.get("data")


def configure_embedding(key: str) -> None:
    api = partial(model_api, key)

    if not any(provider.get("name") == "Ollama" for provider in api("GET", "/providers")):
        api("PUT", "/providers", {"provider_name": "Ollama"})
    instance_name = "nova-pc"
    instances = api("GET", "/providers/Ollama/instances")
    if not any(instance.get("instance_name") == instance_name for instance in instances):
        api("POST", "/providers/Ollama/instances", {
            "instance_name": instance_name, "api_key": "", "region": "",
            "base_url": SHARED_MODEL_URL if SHARED_OLLAMA.exists() else "http://host.docker.internal:11435",
            "model_info": [{"model_name": "bge-m3", "model_type": ["embedding"], "max_tokens": 8192}],
        })
    defaults = api("GET", "/models/default")
    if not any(model.get("model_type") == "embedding" for model in defaults["models"]):
        api("PATCH", "/models/default", {
            "model_provider": "Ollama", "model_instance": instance_name,
            "model_name": "bge-m3", "model_type": "embedding",
        })
    print("Ollama / nova-pc / BGE-M3 已設定；既有有效的預設模型已保留。")


def set_instance_url(key: str, instance_name: str) -> None:
    """Update the endpoint while retaining every selected model and its ID."""
    api = partial(model_api, key)
    path = f"/providers/Ollama/instances/{instance_name}"
    instance = api("GET", path)
    if instance["base_url"] == SHARED_MODEL_URL:
        return
    models = api("GET", path + "/models")
    api("PUT", path, {
        "instance_name": instance["instance_name"], "api_key": instance["api_key"],
        "base_url": SHARED_MODEL_URL, "region": instance.get("region", ""),
        "model_info": [{
            "model_name": model["name"], "model_type": model["model_type"],
            "max_tokens": model.get("max_tokens", 8192), "extra": model.get("extra", {}),
        } for model in models],
        # Connectivity and embeddings are checked before migration. Preserve
        # existing verification metadata and avoid cold-model validation timeouts.
        "verify": False,
    })


def sync_models(key: str | None = None) -> None:
    """Add installed Ollama chat/embedding models without changing defaults."""
    key = key or read_key()
    api = partial(model_api, key)
    local_models = ollama_api("/api/tags")["models"]
    if not any(p.get("name") == "Ollama" for p in api("GET", "/providers")):
        api("PUT", "/providers", {"provider_name": "Ollama"})
    instance_name = "nova-chat"
    instances = api("GET", "/providers/Ollama/instances")
    if not any(i.get("instance_name") == instance_name for i in instances):
        api("POST", "/providers/Ollama/instances", {"instance_name": instance_name})
    set_instance_url(key, instance_name)
    existing = {m["name"] for m in api("GET", "/models")
                if m.get("provider_name") == "Ollama" and m.get("instance_name") == instance_name}
    for model in local_models:
        name = model["name"]
        # Ollama accepts the implicit :latest tag used by older RAGFlow records.
        if name in existing or name.removesuffix(":latest") in existing:
            continue
        capabilities = ollama_api("/api/show", {"model": name}).get("capabilities", [])
        types = (["chat"] if "completion" in capabilities else []) + (
            ["embedding"] if "embedding" in capabilities else []
        )
        if not types:
            continue
        api("POST", f"/providers/Ollama/instances/{instance_name}/models", {
            "model_name": name, "model_type": types, "max_tokens": 8192,
        })
        print(f"RAGFlow 已同步 Ollama 模型：{name}", flush=True)


def watch_models() -> None:
    while True:
        try:
            sync_models()
        except Exception as exc:
            # Do not log credentials or upstream response bodies.
            print(f"RAGFlow 模型同步暫不可用（{type(exc).__name__}）；稍後重試。", flush=True)
        time.sleep(30)


def setup_model_sync() -> None:
    units = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "systemd/user"
    units.mkdir(parents=True, exist_ok=True)
    (units / "nova-ragflow-model-sync.service").write_text(
        "# Copyright (c) 2026 HongXian0903\n# SPDX-License-Identifier: Apache-2.0\n\n"
        "[Unit]\nDescription=Nova Avatar shared Ollama model discovery\n\n"
        f'[Service]\nExecStart=/usr/bin/python3 "{ROOT / "scripts/ragflow_connection.py"}" --watch-models\n'
        "Restart=on-failure\nRestartSec=5\nNoNewPrivileges=yes\nMemoryMax=128M\nCPUQuota=10%\n\n"
        "[Install]\nWantedBy=default.target\n"
    )
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "nova-ragflow-model-sync.service"], check=True)


def unify_models() -> None:
    key = read_key()
    if not works(key):
        raise RuntimeError("RAGFlow API 金鑰無效；請先執行 bash scripts/ragflow.sh connect。")
    local = ollama_api("/api/tags")["models"]
    gateway = subprocess.check_output([
        "docker", "network", "inspect", "bridge", "--format", "{{(index .IPAM.Config 0).Gateway}}",
    ], text=True).strip()
    old_base = f"http://{ipaddress.IPv4Address(gateway)}:11435"
    if not any(m["name"] in ("bge-m3", "bge-m3:latest") for m in local):
        source = ollama_api("/api/show", {"model": "bge-m3"}, base=old_base)
        # Ollama's CLI imports the local GGUF plus its original template and
        # license. No weight download or direct edits to the model store.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".Modelfile") as model_file:
            model_file.write(source["modelfile"])
            model_file.flush()
            env = os.environ.copy()
            env["OLLAMA_HOST"] = "127.0.0.1:11434"
            subprocess.run(["ollama", "create", "bge-m3", "-f", model_file.name], env=env, check=True)
    probe = {"model": "bge-m3", "input": ["共用 Ollama 嵌入一致性驗證"],
             "options": {"use_mmap": True}, "keep_alive": -1}
    vector = ollama_api("/api/embed", probe)["embeddings"][0]
    if len(vector) != 1024:
        raise RuntimeError("BGE-M3 嵌入維度錯誤，尚未切換服務。")
    if not SHARED_OLLAMA.exists():
        original = ollama_api("/api/embed", probe, base=old_base)["embeddings"][0]
        if len(original) != len(vector) or max(abs(a - b) for a, b in zip(original, vector)) > 0.0001:
            raise RuntimeError("BGE-M3 嵌入結果不一致，尚未切換服務。")
    setup_chat_proxy()
    # Move the existing embedding instance without changing knowledge-base
    # references. The chat instance already uses this endpoint.
    instances = model_api(key, "GET", "/providers/Ollama/instances")
    for instance in instances:
        if (instance.get('instance_name') in {'nova-arm64', 'nova-pc'}
                or instance.get('base_url', '').rstrip('/') == 'http://host.docker.internal:11435'):
            set_instance_url(key, instance['instance_name'])
    sync_models(key)
    SHARED_OLLAMA.parent.mkdir(parents=True, exist_ok=True)
    SHARED_OLLAMA.write_text(SHARED_MODEL_URL + "\n")
    subprocess.run(["systemctl", "--user", "disable", "--now", "nova-ragflow-embedding.service"], check=True)
    setup_model_sync()
    print(f"RAGFlow 已統一使用 {SHARED_MODEL_URL}；Ollama 新模型每 30 秒同步一次。")


def setup_chat_proxy() -> None:
    """Forward the Docker bridge to the existing loopback-only Ollama server."""
    result = subprocess.run(
        ["docker", "network", "inspect", "bridge", "--format", "{{(index .IPAM.Config 0).Gateway}}"],
        check=True, capture_output=True, text=True,
    )
    gateway = ipaddress.IPv4Address(result.stdout.strip())
    if not gateway.is_private or gateway.is_unspecified or gateway.is_loopback:
        raise RuntimeError("找不到 Docker 本機橋接位址。")
    proxy = Path("/usr/lib/systemd/systemd-socket-proxyd")
    if not proxy.is_file():
        proxy = Path("/lib/systemd/systemd-socket-proxyd")
    if not proxy.is_file():
        raise RuntimeError("主機缺少 systemd-socket-proxyd。")
    units = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "systemd/user"
    units.mkdir(parents=True, exist_ok=True)
    header = "# Copyright (c) 2026 HongXian0903\n# SPDX-License-Identifier: Apache-2.0\n\n"
    (units / "nova-ragflow-chat-proxy.socket").write_text(header + (
        "[Unit]\nDescription=Nova Avatar RAGFlow chat bridge\n\n"
        f"[Socket]\nListenStream={gateway}:11436\nNoDelay=yes\n\n"
        "[Install]\nWantedBy=sockets.target\n"
    ))
    (units / "nova-ragflow-chat-proxy.service").write_text(header + (
        "[Unit]\nDescription=Nova Avatar RAGFlow chat proxy\n\n"
        f"[Service]\nExecStart={proxy} 127.0.0.1:11434\n"
        "NoNewPrivileges=yes\nMemoryMax=64M\n"
    ))
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "nova-ragflow-chat-proxy.socket"], check=True)


def configure_chat(key: str, model_name: str) -> None:
    api = partial(model_api, key)
    instance_name = "nova-chat"
    models = api("GET", "/models")
    if any(
        model.get("provider_name") == "Ollama" and model.get("instance_name") == instance_name
        and model.get("name") == model_name and "chat" in model.get("model_type", [])
        for model in models
    ):
        print(f"Ollama / {instance_name} / {model_name} 已加入 RAGFlow 聊天模型清單。")
        return
    # RAGFlow verifies the first response within ten seconds. A cold Orin
    # runner needs longer for model loading and its first CUDA kernels.
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps({
            "model": model_name, "messages": [{"role": "user", "content": "Reply OK."}],
            "think": False, "stream": False, "options": {"num_predict": 1}, "keep_alive": "5m",
        }).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:  # noqa: S310 -- fixed loopback URL
        if not json.load(response).get("done"):
            raise RuntimeError(f"本機 Ollama 的 {model_name} 預熱未完成。")
    if not any(provider.get("name") == "Ollama" for provider in api("GET", "/providers")):
        api("PUT", "/providers", {"provider_name": "Ollama"})
    model_info = {"model_name": model_name, "model_type": ["chat"], "max_tokens": 8192}
    instances = api("GET", "/providers/Ollama/instances")
    if not any(instance.get("instance_name") == instance_name for instance in instances):
        api("POST", "/providers/Ollama/instances", {
            "instance_name": instance_name, "api_key": "", "region": "",
            "base_url": "http://host.docker.internal:11436", "model_info": [model_info],
        })
    else:
        api("POST", f"/providers/Ollama/instances/{instance_name}/models", model_info)
    print(f"Ollama / {instance_name} / {model_name} 已加入 RAGFlow 聊天模型清單。")


def connect_chat(model_name: str) -> None:
    key = read_key()
    if not works(key):
        raise RuntimeError("RAGFlow API 金鑰無效；請先執行 bash scripts/ragflow.sh connect。")
    with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=10) as response:
        models = json.load(response).get("models", [])
    if not any(model.get("name") == model_name for model in models):
        raise RuntimeError(f"本機 Ollama 尚未安裝 {model_name}。")
    setup_chat_proxy()
    configure_chat(key, model_name)


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
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--chat-model", help="將已安裝的 Ollama 模型加入 RAGFlow 聊天模型清單")
    actions.add_argument("--unify-models", action="store_true", help="統一 Ollama 模型服務與自動模型清單")
    actions.add_argument("--sync-models", action="store_true", help="立即同步已安裝的 Ollama 模型")
    actions.add_argument("--watch-models", action="store_true", help="持續同步已安裝的 Ollama 模型")
    actions.add_argument("--setup-proxy", action="store_true", help="啟動共用 Ollama 轉送")
    args = parser.parse_args()
    if args.chat_model:
        connect_chat(args.chat_model)
    elif args.unify_models:
        unify_models()
    elif args.sync_models:
        sync_models()
    elif args.watch_models:
        watch_models()
    elif args.setup_proxy:
        setup_chat_proxy()
    else:
        prepare()
