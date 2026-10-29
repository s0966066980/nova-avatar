#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Set the console administrator password; only its scrypt hash is stored."""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.server.admin_password import (  # noqa: E402
    ADMIN_ENV_PATH,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    write_admin_env,
)

password = getpass.getpass(f"控制台管理者密碼（隱藏輸入，至少 {MIN_PASSWORD_LENGTH} 字元；留白取消）：")
if not password:
    raise SystemExit("已取消，原設定未變更。")
if len(password) < MIN_PASSWORD_LENGTH or len(password) > MAX_PASSWORD_LENGTH:
    raise SystemExit(f"密碼長度須介於 {MIN_PASSWORD_LENGTH} 到 {MAX_PASSWORD_LENGTH} 字元，原設定未變更。")
if getpass.getpass("再次輸入確認：") != password:
    raise SystemExit("兩次輸入不一致，原設定未變更。")
write_admin_env(ADMIN_ENV_PATH, password)
print("已寫入 config/admin.env（僅擁有者可讀寫，已排除 Git）。服務立即生效，既有登入需重新登入。")
