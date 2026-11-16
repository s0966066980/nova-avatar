# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Helpers for distinguishing loopback host requests from remote clients."""
from __future__ import annotations

import ipaddress
import os
import sys
from typing import Any


def _header(headers: Any, name: str) -> str:
    if not headers:
        return ""
    target = name.lower()
    if hasattr(headers, "items"):
        for key, value in headers.items():
            if str(key).lower() == target:
                return str(value or "").strip()
    return ""


def is_loopback_ip(raw: str | None) -> bool:
    if not raw or not isinstance(raw, str):
        return False
    cleaned = raw.strip()
    if cleaned.startswith("[") and "]" in cleaned:
        cleaned = cleaned[1:cleaned.index("]")]
    cleaned = cleaned.split("%", 1)[0].strip()
    if not cleaned:
        return False
    if cleaned.lower() == "localhost":
        return True
    try:
        addr = ipaddress.ip_address(cleaned)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_loopback


def is_loopback_request(request: Any) -> bool:
    remote = getattr(request, "remote", None)
    if remote is not None and not is_loopback_ip(str(remote)):
        return False
    forwarded_for = _header(getattr(request, "headers", None), "X-Forwarded-For")
    if forwarded_for:
        first_hop = forwarded_for.split(",", 1)[0].strip()
        if first_hop and not is_loopback_ip(first_hop):
            return False
    return True


def has_local_display() -> bool:
    if sys.platform.startswith("linux"):
        return bool((os.environ.get("DISPLAY") or "").strip())
    return True
