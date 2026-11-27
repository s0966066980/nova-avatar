#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Add a development-only reference recording to the voice library.

The console labels it "開發用，未取得說話者授權" and never selects it by
default. Running it again with the same audio leaves the library unchanged.
Defaults describe the BreezyVoice sample prompt; pass --name/--transcript for
another recording.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.tts import voice_library  # noqa: E402

DEFAULT_NAME = "BreezyVoice 測試音檔（僅開發用）"
DEFAULT_TRANSCRIPT = "在密碼學中，加密是將明文資訊改變為難以讀取的密文內容，使之不可讀的方法。"

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("audio", type=Path, help="參考錄音（WAV、MP3、FLAC、OGG、M4A、WebM）")
parser.add_argument("--name", default=DEFAULT_NAME, help="音訊庫顯示名稱")
parser.add_argument("--transcript", default=DEFAULT_TRANSCRIPT, help="錄音的逐字稿")
parser.add_argument("--voices-dir", type=Path, help="音訊庫資料夾（預設為本專案 data/voices）")
args = parser.parse_args()

if args.voices_dir is not None:
    voice_library.VOICES_ROOT = args.voices_dir.resolve()
known = {voice["id"] for voice in voice_library.list_voices()}
try:
    voice = voice_library.add_voice(args.audio, args.name, args.transcript, development=True)
except voice_library.VoiceLibraryError as exc:
    raise SystemExit(f"無法加入音訊庫：{exc.message}") from None
state = "已存在" if voice["id"] in known else "已加入"
flag = "（開發用）" if voice["development"] else "（音訊庫已有同一段錄音，未標記開發用）"
print(f"{state} {voice_library.voices_root() / voice['id']}.wav：{voice['name']}{flag}")
