# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""RAGFlow ids this layer puts into request paths; the core validated the scope."""
import re

_ID = re.compile(r"[a-fA-F0-9]{32}")


def ragflow_id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("知識庫或文件識別碼不正確")
    return value
