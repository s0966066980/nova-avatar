#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Correct NVIDIA cuSPARSELt's SBSA wheel tag after verifying its ARM64 ELF."""

import base64
import csv
import hashlib
import importlib.metadata
import io
import platform


def main() -> None:
    if platform.machine() != "aarch64":
        return
    distribution = importlib.metadata.distribution("nvidia-cusparselt-cu13")
    wheel = next(distribution.locate_file(path) for path in distribution.files if str(path).endswith(".dist-info/WHEEL"))
    text = wheel.read_text()
    wrong_tag = "Tag: py3-none-manylinux2014_sbsa"
    if wrong_tag not in text:
        return
    library = distribution.locate_file("nvidia/cusparselt/lib/libcusparseLt.so.0")
    with library.open("rb") as handle:
        header = handle.read(20)
    # ELF64, little endian, EM_AARCH64. No binary or license changes.
    if header[:6] != b"\x7fELF\x02\x01" or int.from_bytes(header[18:20], "little") != 183:
        raise RuntimeError("cuSPARSELt is not an ARM64 ELF; reinstall the correct wheel")
    data = text.replace(wrong_tag, "Tag: py3-none-manylinux2014_aarch64").encode()
    wheel.write_bytes(data)
    record = wheel.with_name("RECORD")
    rows = list(csv.reader(io.StringIO(record.read_text())))
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    for row in rows:
        if row[0] == f"{wheel.parent.name}/WHEEL":
            row[1:] = [f"sha256={digest}", str(len(data))]
    with record.open("w", newline="") as handle:
        csv.writer(handle).writerows(rows)
    print("Corrected cuSPARSELt ARM64 wheel metadata; preserved the native library")


if __name__ == "__main__":
    main()
