# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Live red/green probe of the actual Nova search entry point; public synthetic query."""
import asyncio
from src.web_search.service import search

async def main():
    result = await search('Python official downloads')
    print(f"status={result['status']} sources={len(result['sources'])}", flush=True)
    assert result['sources'], 'Nova search returned no sources for a known public query'
    assert any(s['kind'] == 'page' for s in result['sources']), 'No result page was read'

asyncio.run(main())
