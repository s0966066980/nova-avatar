# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Console administrator password hash stored in the gitignored config/admin.env.

Standard library only, so scripts/configure-admin.py can import it without the
server's model dependencies.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import tempfile
from pathlib import Path

ADMIN_ENV_PATH = Path(__file__).resolve().parents[2] / "config" / "admin.env"
ADMIN_ENV_KEY = "NOVA_ADMIN_PASSWORD_HASH"
CONFIGURE_COMMAND = "uv run python scripts/configure-admin.py"
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 1024

# scrypt cost: about 16 MiB and tens of milliseconds per attempt.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_KEY_BYTES = 32
_MAX_MEMORY = 64 * 1024**2


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int, length: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=length, maxmem=_MAX_MEMORY)


def hash_password(password: str) -> str:
    """Return ``scrypt$n$r$p$salt$key`` for ``password``."""
    salt = secrets.token_bytes(16)
    key = _scrypt(password, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P, _KEY_BYTES)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64encode(salt)}${_b64encode(key)}"


def verify_password(password: str, encoded: str | None) -> bool:
    """Constant-time check of ``password`` against a ``hash_password`` value."""
    if not encoded or len(password) > MAX_PASSWORD_LENGTH:
        return False
    try:
        scheme, n, r, p, salt, key = encoded.split("$")
        if scheme != "scrypt":
            return False
        expected = _b64decode(key)
        actual = _scrypt(password, _b64decode(salt), int(n), int(r), int(p), len(expected))
    except (ValueError, TypeError, MemoryError):
        return False
    return hmac.compare_digest(actual, expected)


def read_password_hash(path: Path) -> str | None:
    """The stored hash, or None when the file or the key is missing."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return None
    for line in text.splitlines():
        name, sep, value = line.strip().partition("=")
        if sep and name.strip() == ADMIN_ENV_KEY and value.strip():
            return value.strip()
    return None


def write_admin_env(path: Path, password: str) -> None:
    """Atomically replace ``path`` with ``password``'s hash, readable by the owner only."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"{ADMIN_ENV_KEY}={hash_password(password)}\n"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(line)
        temporary = handle.name
    os.replace(temporary, path)
