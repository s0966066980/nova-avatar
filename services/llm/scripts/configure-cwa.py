#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Store the existing CWA credential locally without echoing it or invoking a shell."""
import getpass
import os
from pathlib import Path
import tempfile

path = Path(__file__).resolve().parents[1] / "config/cwa.env"
key = getpass.getpass("CWA 授權碼（隱藏輸入；留白取消）：").strip()
if not key:
    raise SystemExit("已取消，原設定未變更。")
if not key.startswith("CWA-") or any(c.isspace() for c in key) or len(key) > 200:
    raise SystemExit("授權碼格式不正確。")
path.parent.mkdir(parents=True, exist_ok=True)
with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
    os.fchmod(handle.fileno(), 0o600)
    handle.write("NOVA_CWA_API_KEY=" + key + "\n")
    temporary = handle.name
os.replace(temporary, path)
print("已寫入 config/cwa.env（僅擁有者可讀寫，已排除 Git）。服務將於下次查詢讀取，無需重啟。")
