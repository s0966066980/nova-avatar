import asyncio
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
sys.path.insert(0, str(REPO))
# Keep the repository logger's relative output confined to this probe directory.
os.chdir(ROOT)
from probe import SAMPLES

async def main():
    from src.tts.engines.edge import _edge_communicate
    from src.tts.edge_connection import EdgeConnectionPool
    results = []
    pool = EdgeConnectionPool()
    try:
        for variant in ('nova-adapter', 'persistent-pool'):
            for lang, voice, text in SAMPLES:
                started = time.monotonic()
                data = bytearray()
                result = {'variant': variant, 'language': lang, 'voice': voice}
                try:
                    async def collect():
                        if variant == 'nova-adapter':
                            async for item in _edge_communicate(text, voice).stream():
                                if item['type'] == 'audio': data.extend(item['data'])
                        else:
                            async for item in pool.stream(text, voice):
                                if item['type'] == 'audio': data.extend(item['data'])
                    await asyncio.wait_for(collect(), 25)
                    assert len(data) > 1000, f'Only {len(data)} speech bytes'
                    path = ROOT / f'{variant}-{lang}.mp3'
                    path.write_bytes(data)
                    result.update(ok=True, bytes=len(data), artifact=path.name, idle_connections=pool.idle_count)
                except Exception as exc:
                    result.update(ok=False, error=type(exc).__name__, status=getattr(exc,'status',None))
                result['seconds'] = round(time.monotonic()-started,3)
                results.append(result)
                print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        await pool.close()
    (ROOT/'product-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    return 0 if all(r['ok'] for r in results) else 1

if __name__=='__main__':
    sys.exit(asyncio.run(main()))
