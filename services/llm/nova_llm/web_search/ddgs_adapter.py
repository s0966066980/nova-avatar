# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""The only dependency on DDGS 9.14.4's private engine/client interfaces.

That version chooses a random DuckDuckGo User-Agent at import time. Some values
receive a 202 challenge even though a minimal search request succeeds. Default
pagination/region fields can also affect that response. Configure
only this request's engine instance; never patch package files or global headers.
"""
from importlib.metadata import version

PINNED_VERSION = '9.14.4'
DUCKDUCKGO_AGENT = 'Mozilla/5.0'
ALLOWED_ENGINES = frozenset({'duckduckgo', 'brave'})


class SearchUnavailable(RuntimeError):
    """A safe machine-readable reason, without headers, response body or query."""
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class _ObservedTransport:
    def __init__(self, transport, *, duckduckgo=False):
        self.transport = transport
        self.duckduckgo = duckduckgo
        self.status = None

    def __getattr__(self, name):
        return getattr(self.transport, name)

    def request(self, *args, **kwargs):
        if self.duckduckgo and isinstance(kwargs.get('data'), dict):
            # The empty pagination token plus the default region together can
            # trigger a challenge. Keep the public query and explicit filters,
            # using DDG's own default region instead of sending redundant ones.
            data = dict(kwargs['data'])
            if data.get('b') == '':
                data.pop('b')
            if data.get('l') == 'us-en':
                data.pop('l')
            kwargs['data'] = data
        response = self.transport.request(*args, **kwargs)
        self.status = response.status_code
        return response


def search(query, engine, timeout):
    if engine not in ALLOWED_ENGINES:
        raise SearchUnavailable('engine_not_allowed')
    if version('ddgs') != PINNED_VERSION:
        raise SearchUnavailable('incompatible_ddgs')
    from ddgs.ddgs import DDGS
    from ddgs.engines import ENGINES
    from ddgs.exceptions import DDGSException

    engine_class = ENGINES.get('text', {}).get(engine)
    if engine_class is None:
        # DDGS otherwise silently falls back to auto and contacts other engines.
        raise SearchUnavailable('engine_missing')
    client = DDGS(timeout=max(.1, timeout))
    if not isinstance(getattr(client, '_engines_cache', None), dict):
        raise SearchUnavailable('incompatible_ddgs')
    # DDGS may share a distributed API client across instances. This integration
    # is deliberately local orchestration with only the two approved providers.
    if getattr(DDGS, '_network_client', None) is not None:
        raise SearchUnavailable('unexpected_network_client')
    provider = engine_class(timeout=max(.1, timeout))
    transport = getattr(provider, 'http_client', None)
    http_client = getattr(transport, 'client', None)
    try:
        if transport is None or http_client is None or not callable(getattr(transport, 'request', None)):
            raise SearchUnavailable('incompatible_ddgs')
        if engine == 'duckduckgo':
            headers = getattr(http_client, 'headers', None)
            if headers is None:
                raise SearchUnavailable('incompatible_ddgs')
            headers['User-Agent'] = DUCKDUCKGO_AGENT
        observed = _ObservedTransport(transport, duckduckgo=engine == 'duckduckgo')
        provider.http_client = observed
        client._engines_cache[engine_class] = provider
        try:
            return list(client.text(query, backend=engine, max_results=5, safesearch='moderate'))[:5]
        except DDGSException as exc:
            if observed.status == 202:
                raise SearchUnavailable('challenge') from exc
            if observed.status == 429:
                raise SearchUnavailable('rate_limited') from exc
            if observed.status == 200 and str(exc) == 'No results found.':
                return []
            raise SearchUnavailable('request_failed') from exc
    finally:
        close = getattr(http_client, 'close', None)
        if callable(close):
            close()
