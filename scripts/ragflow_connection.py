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
# BGE-M3 on the CPU-only llama.cpp server (scripts/ragflow_llamacpp_embedding.sh).
EMBEDDING_PROVIDER = "OpenAI-API-Compatible"
EMBEDDING_INSTANCE = "nova-llamacpp"
EMBEDDING_MODEL = "bge-m3"
EMBEDDING_URL = "http://host.docker.internal:11437/v1"
EMBEDDING_MAX_TOKENS = 2048  # the server's single micro-batch
LEGACY_EMBEDDING_UNIT = "nova-ragflow-embedding.service"
# Same GGUF on both servers: vectors match to ~1.0 (issue 15). Anything lower
# means a different model and the stored chunks would need re-parsing.
MIN_SWITCH_COSINE = 0.99


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


def ensure_embedding_model(key: str) -> str:
    """Register the llama.cpp BGE-M3 endpoint once; return its tenant model ID."""
    api = partial(model_api, key)
    if not any(provider.get("name") == EMBEDDING_PROVIDER for provider in api("GET", "/providers")):
        api("PUT", "/providers", {"provider_name": EMBEDDING_PROVIDER})
    instances = api("GET", f"/providers/{EMBEDDING_PROVIDER}/instances")
    if not any(instance.get("instance_name") == EMBEDDING_INSTANCE for instance in instances):
        # RAGFlow verifies the endpoint with a real embedding before saving.
        # Its OpenAI client needs a non-empty key; like the Ollama it replaces,
        # the server has no auth and listens only on the Docker bridge.
        api("POST", f"/providers/{EMBEDDING_PROVIDER}/instances", {
            "instance_name": EMBEDDING_INSTANCE, "api_key": "x", "region": "",
            "base_url": EMBEDDING_URL,
            "model_info": [{"model_name": EMBEDDING_MODEL, "model_type": ["embedding"],
                            "max_tokens": EMBEDDING_MAX_TOKENS}],
        })
    for model in api("GET", "/models"):
        if (model.get("provider_name"), model.get("instance_name"), model.get("name")) == (
                EMBEDDING_PROVIDER, EMBEDDING_INSTANCE, EMBEDDING_MODEL):
            return model["model_id"]
    raise RuntimeError("RAGFlow 未列出 llama.cpp 的 BGE-M3 嵌入模型。")


def set_default_embedding(key: str) -> None:
    model_api(key, "PATCH", "/models/default", {
        "model_provider": EMBEDDING_PROVIDER, "model_instance": EMBEDDING_INSTANCE,
        "model_name": EMBEDDING_MODEL, "model_type": "embedding",
    })


def configure_embedding(key: str) -> None:
    ensure_embedding_model(key)
    defaults = model_api(key, "GET", "/models/default")
    if not any(model.get("model_type") == "embedding" for model in defaults["models"]):
        set_default_embedding(key)
    print(f"{EMBEDDING_PROVIDER} / {EMBEDDING_INSTANCE} / BGE-M3（llama.cpp CPU）已設定；"
          "既有有效的預設模型已保留。")


def _uses_bge_m3(dataset: dict) -> bool:
    # embedding_model_name is "<model>@<instance>@<provider>".
    return dataset.get("embedding_model_name", "").split("@", 1)[0] in {"bge-m3", "bge-m3:latest"}


def _paged(key: str, path: str, field: str | None = None) -> list:
    items, page = [], 1
    while True:  # RAGFlow caps page_size at 100.
        data = model_api(key, "GET", f"{path}?page={page}&page_size=100")
        batch = data[field] if field else data
        items += batch
        if len(batch) < 100:
            return items
        page += 1


def _backup_embedding_settings(key: str) -> Path:
    api = partial(model_api, key)
    datasets = _paged(key, "/datasets")
    snapshot = {
        "datasets": datasets,
        "documents": {d["id"]: _paged(key, f"/datasets/{d['id']}/documents", "docs") for d in datasets},
        "defaults": api("GET", "/models/default")["models"],
    }
    backups = ROOT / ".local/ragflow/backups"
    backups.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = backups / f"embedding-switch-{stamp}.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(snapshot, output, ensure_ascii=False, indent=1)
    return path


def switch_embedding(key: str | None = None) -> None:
    """Move BGE-M3 datasets to the llama.cpp server, then stop the GPU Ollama.

    Settings are backed up first. Each dataset with chunks must pass RAGFlow's
    stored-vector comparison before its embedding model changes, so no
    document is re-parsed or deleted. The GPU service stops only after a
    retrieval through every switched dataset succeeds.
    """
    if key is None:
        key = read_key()
        if not works(key):
            raise RuntimeError("RAGFlow API 金鑰無效；請先執行 bash scripts/ragflow.sh connect。")
    api = partial(model_api, key)
    backup = _backup_embedding_settings(key)
    print(f"已備份知識庫與預設模型設定：{backup}")
    new_id = ensure_embedding_model(key)
    targets = [d for d in _paged(key, "/datasets") if _uses_bge_m3(d)]
    for dataset in targets:
        if dataset["embedding_model"] == new_id or not dataset.get("chunk_count"):
            continue
        check = api("POST", f"/datasets/{dataset['id']}/embedding/check", {"embd_id": new_id})
        if check["summary"]["min_cos_sim"] < MIN_SWITCH_COSINE:
            raise RuntimeError(f"知識庫 {dataset['name']} 的新舊向量不一致，未切換。")
    for dataset in targets:
        if dataset["embedding_model"] != new_id:
            api("PUT", f"/datasets/{dataset['id']}", {"embedding_model": new_id})
            print(f"知識庫 {dataset['name']} 已改用 llama.cpp BGE-M3。")
    set_default_embedding(key)
    for dataset in targets:
        api("POST", "/retrieval", {"question": "嵌入服務切換驗證", "dataset_ids": [dataset["id"]],
                                   "page_size": 1})
    subprocess.run(["systemctl", "--user", "disable", "--now", LEGACY_EMBEDDING_UNIT], check=False)
    print(f"檢索已通過 llama.cpp 嵌入服務；已停用 {LEGACY_EMBEDDING_UNIT}（單元檔保留供還原）。")


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
    """Add installed Ollama chat models without changing defaults.

    Embedding-only models are skipped: RAGFlow embeds with the llama.cpp server.
    """
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
        if "completion" not in capabilities:
            continue
        api("POST", f"/providers/Ollama/instances/{instance_name}/models", {
            "model_name": name, "model_type": ["chat"], "max_tokens": 8192,
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
    """Serve RAGFlow's chat models from the host Ollama; embeddings stay on llama.cpp."""
    key = read_key()
    if not works(key):
        raise RuntimeError("RAGFlow API 金鑰無效；請先執行 bash scripts/ragflow.sh connect。")
    ollama_datasets = [d["name"] for d in _paged(key, "/datasets")
                       if d.get("embedding_model_name", "").endswith("@Ollama")]
    if ollama_datasets:
        raise RuntimeError("知識庫仍使用 Ollama 嵌入（" + "、".join(ollama_datasets)
                           + "）；請先執行 bash scripts/ragflow.sh switch-embedding。")
    setup_chat_proxy()
    # Old instances on the retired GPU embedding Ollama (11435) also carry
    # chat models; repoint them so those models stay usable.
    # The instance list omits base_url; read each instance.
    for instance in model_api(key, "GET", "/providers/Ollama/instances"):
        name = instance['instance_name']
        base_url = model_api(key, "GET", f"/providers/Ollama/instances/{name}").get("base_url", "")
        if name in {'nova-arm64', 'nova-pc'} or base_url.rstrip('/') == 'http://host.docker.internal:11435':
            set_instance_url(key, name)
    sync_models(key)
    SHARED_OLLAMA.parent.mkdir(parents=True, exist_ok=True)
    SHARED_OLLAMA.write_text(SHARED_MODEL_URL + "\n")
    setup_model_sync()
    print(f"RAGFlow 聊天模型已統一使用 {SHARED_MODEL_URL}；Ollama 新模型每 30 秒同步一次。")


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
    actions.add_argument("--switch-embedding", action="store_true",
                         help="將 BGE-M3 知識庫改用 llama.cpp CPU 嵌入服務")
    actions.add_argument("--unify-models", action="store_true", help="統一 Ollama 聊天模型服務與自動模型清單")
    actions.add_argument("--sync-models", action="store_true", help="立即同步已安裝的 Ollama 模型")
    actions.add_argument("--watch-models", action="store_true", help="持續同步已安裝的 Ollama 模型")
    actions.add_argument("--setup-proxy", action="store_true", help="啟動共用 Ollama 轉送")
    args = parser.parse_args()
    if args.chat_model:
        connect_chat(args.chat_model)
    elif args.switch_embedding:
        switch_embedding()
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
