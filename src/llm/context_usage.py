# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Observe the deployed context and reject oversized requests without pruning."""
from __future__ import annotations

import time
from threading import RLock

import requests


class ContextCapacityError(ValueError):
    pass


_capacities: dict[str, tuple[float, int | None]] = {}
_lock = RLock()


def _root(base_url: str) -> str:
    return base_url.rstrip('/').removesuffix('/v1')


def deployed_capacity(base_url: str, *, refresh: bool = False) -> int | None:
    root = _root(base_url)
    with _lock:
        cached = _capacities.get(root)
    if not refresh and cached and time.monotonic() - cached[0] < 15:
        return cached[1]
    result = None
    try:
        response = requests.get(root + '/props', timeout=1)
        response.raise_for_status()
        value = response.json().get('default_generation_settings', {}).get('n_ctx')
        if isinstance(value, int) and value > 0:
            result = value
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        pass
    with _lock:
        _capacities[root] = (time.monotonic(), result)
    return result


def _estimate(text: str) -> int:
    # A labelled approximation, never presented as tokenizer output.
    return sum(1 if ord(c) > 127 else 0.25 for c in text).__ceil__()


def measure_request(base_url: str, messages: list[dict], output_budget: int,
                    *, local: bool, model: str, template_options: dict | None = None) -> dict:
    history_text = '\n'.join(str(m.get('content', '')) for m in messages[1:-1])
    total_text = '\n'.join(str(m.get('content', '')) for m in messages)
    result = {
        'model': model, 'capacity': None, 'input_tokens': _estimate(total_text) + 4 * len(messages),
        'history_tokens': _estimate(history_text), 'history_estimated': True,
        'reserved_output_tokens': output_budget, 'estimated': True,
        'source': 'estimate', 'observed_at': time.time(),
    }
    if local:
        result['capacity'] = deployed_capacity(base_url)
        try:
            root = _root(base_url)
            templated = requests.post(root + '/apply-template', json={
                **(template_options or {}), 'messages': messages,
            }, timeout=2)
            templated.raise_for_status()
            prompt = templated.json()['prompt']
            tokenized = requests.post(root + '/tokenize', json={
                'content': prompt, 'add_special': True, 'parse_special': True,
            }, timeout=2)
            tokenized.raise_for_status()
            result.update(input_tokens=len(tokenized.json()['tokens']), estimated=False,
                          source='llama.cpp tokenizer + chat template')
        except (requests.RequestException, KeyError, ValueError, TypeError):
            pass
    capacity = result['capacity']
    used = result['input_tokens'] + output_budget
    result['remaining_tokens'] = max(0, capacity - used) if capacity else None
    result['usage_percent'] = round(used / capacity * 100, 1) if capacity else None
    result['other_input_tokens'] = max(0, result['input_tokens'] - result['history_tokens'])
    result['over_capacity'] = bool(capacity and used > capacity)
    return result
