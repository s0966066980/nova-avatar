# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Create private, repeatable RAGFlow Compose settings from the pinned tag."""
from __future__ import annotations

import os
import re
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / ".local" / "ragflow" / "upstream"
ENV_FILE = UPSTREAM / "docker" / ".env"
MANAGED_MARKER = "# NOVA_RAGFLOW_MANAGED=1"


def _stock_env() -> str:
    completed = subprocess.run(
        ["git", "-C", str(UPSTREAM), "show", "HEAD:docker/.env"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def prepare() -> Path:
    """Preserve an existing managed file; never overwrite manual secrets."""
    stock = _stock_env()
    current = ENV_FILE.read_text(encoding="utf-8")
    if current.startswith(MANAGED_MARKER):
        ENV_FILE.chmod(0o600)
        return ENV_FILE
    if current != stock:
        raise RuntimeError("RAGFlow .env 已被手動修改；不覆寫現有設定")

    passwords = {
        key: secrets.token_hex(24)
        for key in (
            "ELASTIC_PASSWORD",
            "SERENEDB_PASSWORD",
            "OCEANBASE_PASSWORD",
            "SEEKDB_PASSWORD",
            "MYSQL_PASSWORD",
            "MINIO_PASSWORD",
            "REDIS_PASSWORD",
            "CLICKHOUSE_PASSWORD",
            "ADMIN_DEFAULT_PASSWORD",
        )
    }
    passwords["OPENSEARCH_PASSWORD"] = "Aa1!" + secrets.token_hex(22)
    values = {
        **passwords,
        "DOC_ENGINE": "elasticsearch",
        "DB_TYPE": "mysql",
        "DEVICE": "cpu",
        "METADATA_DB_PROFILE": "mysql",
        "COMPOSE_PROFILES": "elasticsearch,cpu,metadata-mysql",
        "MEM_LIMIT": "6442450944",
        "DOC_BULK_SIZE": "1",
        "EMBEDDING_BATCH_SIZE": "4",
        "RAGFLOW_IMAGE": "infiniflow/ragflow:v0.27.2",
        "TZ": "Asia/Taipei",
    }
    for key, value in values.items():
        stock, count = re.subn(rf"(?m)^{key}=.*$", lambda _: f"{key}={value}", stock)
        if count != 1:
            raise RuntimeError(f"RAGFlow 上游 .env 缺少唯一的 {key} 欄位")
    managed = f"{MANAGED_MARKER}\n{stock}"
    fd, path = tempfile.mkstemp(prefix=".nova-ragflow-", dir=ENV_FILE.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(managed)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(path, ENV_FILE)
    except BaseException:
        if os.path.exists(path):
            os.unlink(path)
        raise
    return ENV_FILE


if __name__ == "__main__":
    try:
        prepare()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"準備 RAGFlow 設定失敗：{exc}", file=sys.stderr)
        raise SystemExit(1)
    print("RAGFlow 私有設定已準備完成；密碼未輸出。")
