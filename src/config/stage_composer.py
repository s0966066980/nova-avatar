# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Persistent stage composer appearance shared by settings and overrides."""
DEFAULTS = {
    'composer_enabled': False, 'composer_x': 50, 'composer_y': 78,
    'composer_width': 90, 'composer_height': 220, 'composer_font_size': 16, 'composer_opacity': 92,
    'composer_placeholder_zh': '輸入問題，或附上 PDF／圖片',
    'composer_placeholder_en': 'Ask a question or attach a PDF / image',
}


def snapshot(stage):
    return {key: getattr(stage, key, default) for key, default in DEFAULTS.items()}


def validate(payload, stage):
    values = snapshot(stage)
    for key in DEFAULTS:
        if key not in payload:
            continue
        value = payload[key]
        if key == 'composer_enabled':
            if not isinstance(value, bool):
                raise ValueError('輸入功能開關須為布林值')
        elif 'placeholder' in key:
            if not isinstance(value, str) or not value.strip() or len(value) > 200:
                raise ValueError('輸入提示須為 1–200 字文字')
        else:
            bounds = {'composer_width': (40, 100), 'composer_height': (120, 480),
                      'composer_font_size': (12, 28)}.get(key, (0, 100))
            if isinstance(value, bool) or not isinstance(value, int) or not bounds[0] <= value <= bounds[1]:
                raise ValueError(f'{key} 須為 {bounds[0]}–{bounds[1]} 的整數')
        values[key] = value
    return values
