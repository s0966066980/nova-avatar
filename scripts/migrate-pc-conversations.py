#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Apply the accepted PC conversation defaults, retaining a private backup."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def migrate(path: Path, *, backup_dir: Path) -> Path | None:
    if path.is_symlink():
        raise ValueError('設定檔不可為符號連結')
    original = path.read_bytes() if path.exists() else b''
    values = yaml.safe_load(original) or {}
    if not isinstance(values, dict):
        raise ValueError('設定檔必須是物件')
    stage = {**values.get('stage', {}), 'clear_display_seconds': 15,
             'idle_reset_seconds': 60, 'idle_greeting_seconds': 30}
    asr = {**values.get('asr', {}), 'type': 'whisper', 'model_size': 'small', 'language': 'auto'}
    if values.get('stage') == stage and values.get('asr') == asr:
        return None
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = backup_dir / f'{path.name}.{stamp}.bak'
    backup.write_bytes(original)
    os.chmod(backup, 0o600)
    values.update(stage=stage, asr=asr)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         delete=False) as target:
            name = target.name
            yaml.safe_dump(values, target, allow_unicode=True, sort_keys=False)
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if name and Path(name).exists():
            Path(name).unlink()
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--path', type=Path)
    args = parser.parse_args()
    from src.config.overrides import RUNTIME_OVERRIDES_FILE
    path = args.path or RUNTIME_OVERRIDES_FILE
    backup = migrate(path, backup_dir=ROOT / '.local/jetson-to-pc-port/backups')
    if backup:
        print(f'已套用 15／60／30 秒與 Whisper small／auto；原設定備份：{backup}')
    else:
        print('設定已符合本次移植預設，未重寫。')


if __name__ == '__main__':
    main()
