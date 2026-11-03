# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Live regression: a factual lookup must not require the visitor to say 'search'."""
import asyncio
import json
import socket
import sys
from src.config.schema import Config
from src.llm.llamacpp import ensure_server, shutdown_llama_server
from src.web_search.planner import plan

async def main():
    config = Config()
    config.llm.provider = 'llamacpp'
    config.llm.model = 'gemma-4-E2B_q4_0-it'
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    config.llm.base_url = ensure_server(config.llm.model, port=port, ctx=8192)
    question = sys.argv[1] if len(sys.argv) > 1 else '鳳凰谷鳥園的團體導覽要多少人才能預約？'
    decision = await plan(config, question, [])
    print(json.dumps({'question': question, 'decision': decision}, ensure_ascii=False), flush=True)
    assert decision['search'], 'A specific public fact needing verification did not trigger search'
try:
    asyncio.run(main())
finally:
    shutdown_llama_server()
