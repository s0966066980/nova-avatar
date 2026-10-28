# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Bounded local OCR supplements page vision; no document leaves this host."""
from io import BytesIO
import os
import shutil
import subprocess


def extract_image_text(image):
    binary = shutil.which('tesseract')
    if binary is None:
        return '[Local OCR unavailable; small printed text may be unreliable.]'
    copy = image.copy()
    copy.thumbnail((1536, 1536))
    buffer = BytesIO()
    copy.save(buffer, format='PNG')
    copy.close()
    try:
        result = subprocess.run([binary, 'stdin', 'stdout', '-l', 'chi_tra+eng', '--psm', '6'],
            input=buffer.getvalue(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=20, check=True, env={**os.environ, 'OMP_THREAD_LIMIT': '1'})
        return result.stdout.decode('utf-8', errors='replace')[:6000]
    except (OSError, subprocess.SubprocessError):
        return '[Local OCR could not read this image; do not invent unreadable text.]'
