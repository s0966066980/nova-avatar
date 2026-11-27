# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Pick FFmpeg's audio demuxer from an upload's magic bytes.

Every PyAV open of untrusted audio names its demuxer explicitly. Left to
probe, FFmpeg also recognises playlist and concat formats, which open the
files they list, so an upload could make the server read other files.
"""

from __future__ import annotations

# Bytes needed by demuxer_for().
HEADER_BYTES = 12


def demuxer_for(head: bytes) -> str | None:
    """The demuxer for a supported audio container, or None for anything else."""
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:4] == b"fLaC":
        return "flac"
    if head[:4] == b"OggS":
        return "ogg"
    if head[4:8] == b"ftyp":
        return "mp4"
    if head[:4] == b"\x1aE\xdf\xa3":  # Matroska / WebM (browser recordings)
        return "matroska"
    if head[:3] == b"ID3" or (len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "mp3"
    return None
