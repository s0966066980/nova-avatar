# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Observe the deployed context without delaying the answer or pruning history.

The deployed size is asked once per model load; each request is estimated
locally and the provider's reported usage replaces the estimate afterwards.
"""
from __future__ import annotations

import time
from threading import RLock, Thread

import requests


class ContextCapacityError(ValueError):
    pass


# A successful /props answer stays valid until the model is loaded or
# switched (``deployed_capacity(refresh=True)``); failures are retried later.
_capacities: dict[str, int] = {}
_failed_at: dict[str, float] = {}
_refreshing: set[str] = set()
_lock = RLock()
_RETRY_SECONDS = 15


def _root(base_url: str) -> str:
    return base_url.rstrip('/').removesuffix('/v1')


def deployed_capacity(base_url: str, *, refresh: bool = False) -> int | None:
    """The deployed n_ctx; asks llama-server only on refresh or a cache miss."""
    root = _root(base_url)
    with _lock:
        cached = _capacities.get(root)
        failed_at = _failed_at.get(root)
    if not refresh and cached is not None:
        return cached
    if not refresh and failed_at is not None and time.monotonic() - failed_at < _RETRY_SECONDS:
        return None
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
        if result is None:
            # A reloaded model must never keep the previous model's size.
            _capacities.pop(root, None)
            _failed_at[root] = time.monotonic()
        else:
            _capacities[root] = result
            _failed_at.pop(root, None)
    return result


def cached_capacity(base_url: str) -> int | None:
    """The cached n_ctx without any request; a miss refreshes in the background."""
    root = _root(base_url)
    with _lock:
        cached = _capacities.get(root)
        failed_at = _failed_at.get(root)
        if cached is not None or root in _refreshing or (
                failed_at is not None and time.monotonic() - failed_at < _RETRY_SECONDS):
            return cached
        _refreshing.add(root)

    def refresh():
        try:
            deployed_capacity(base_url, refresh=True)
        finally:
            with _lock:
                _refreshing.discard(root)
    Thread(target=refresh, name='llm-context-capacity', daemon=True).start()
    return None


def _estimate(text: str) -> int:
    # A labelled approximation, never presented as tokenizer output.
    return sum(1 if ord(c) > 127 else 0.25 for c in text).__ceil__()


def measure_request(messages: list[dict], output_budget: int, *,
                    capacity: int | None, model: str) -> dict:
    """Estimate this request locally; no request reaches the model server.

    The provider's usage replaces the estimate once the reply has streamed.
    """
    def text_content(message):
        content = message.get('content', '')
        return ('\n'.join(p.get('text', '') for p in content if p.get('type') == 'text')
                if isinstance(content, list) else str(content))
    images = sum(1 for m in messages if isinstance(m.get('content'), list)
                 for part in m['content'] if part.get('type') == 'image_url')
    history_text = '\n'.join(text_content(m) for m in messages[1:-1])
    total_text = '\n'.join(text_content(m) for m in messages)
    result = {
        'model': model, 'capacity': capacity,
        'history_tokens': _estimate(history_text), 'history_estimated': True,
        'reserved_output_tokens': output_budget, 'estimated': True,
        # Text estimates cannot measure mtmd image embeddings.
        'source': 'text estimate; visual tokens pending provider usage' if images else 'estimate',
        'observed_at': time.time(),
        'image_count': images, 'visual_tokens_unknown': bool(images),
    }
    return with_input_tokens(result, _estimate(total_text) + 4 * len(messages))


def with_input_tokens(usage: dict, input_tokens: int) -> dict:
    """Set the input size and recompute every field derived from it."""
    capacity = usage['capacity']
    used = input_tokens + usage['reserved_output_tokens']
    usage.update(
        input_tokens=input_tokens,
        remaining_tokens=max(0, capacity - used) if capacity else None,
        usage_percent=round(used / capacity * 100, 1) if capacity else None,
        other_input_tokens=max(0, input_tokens - usage['history_tokens']),
        over_capacity=bool(capacity and used > capacity),
    )
    return usage
