# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Refuse a Compose plan that escapes Nova's local RAGFlow boundary."""
from __future__ import annotations

import json
import sys

# Tag plus registry digest: a re-pushed tag cannot change the running image.
RAGFLOW_IMAGE = (
    "infiniflow/ragflow:v0.27.2"
    "@sha256:e6b3f1a185c0a70abb3a72e1092415df8c5c6a4fae0089545554f2936c4b27ab"
)
EXPECTED_SERVICES = {
    "ragflow-cpu", "es01", "mysql", "minio", "redis"
}
EXPECTED_PORTS = {
    ("ragflow-cpu", "127.0.0.1", "8088", 80),
    ("ragflow-cpu", "127.0.0.1", "9380", 9380),
}


def validate(plan: dict) -> None:
    services = plan.get("services", {})
    if set(services) != EXPECTED_SERVICES:
        raise ValueError("啟用服務清單與固定的 RAGFlow 部署不符")
    published = {
        (name, port.get("host_ip"), str(port.get("published")), port.get("target"))
        for name, service in services.items()
        for port in service.get("ports", [])
    }
    if published != EXPECTED_PORTS:
        raise ValueError("對主機開放的連接埠不符合本機隔離規則")
    if services["ragflow-cpu"].get("image") != RAGFLOW_IMAGE:
        raise ValueError("RAGFlow 映像版本或 digest 與固定版本不符")
    for name, service in services.items():
        if "ragflow" not in service.get("networks", {}):
            raise ValueError(f"{name} 未在獨立 RAGFlow 網路中")
        if not service.get("mem_limit") or not service.get("cpus"):
            raise ValueError(f"{name} 缺少資源上限")


if __name__ == "__main__":
    try:
        validate(json.load(sys.stdin))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"RAGFlow Compose 安全檢查失敗：{exc}", file=sys.stderr)
        raise SystemExit(1)
    print("RAGFlow Compose 服務、映像、連接埠與資源上限符合隔離規則。")
