import asyncio
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
SAMPLES = [('en', 'en-US-JennyNeural', 'Hello. This is a short speech connection test.'),
           ('zh', 'zh-TW-HsiaoChenNeural', '您好，這是一段語音連線測試。')]

async def main():
    import edge_tts
    from edge_tts import communicate
    from urllib.parse import urlsplit
    print(json.dumps({'version': importlib.metadata.version('edge-tts'),
        'endpoint': urlsplit(communicate.WSS_URL)._replace(query='').geturl(),
        'proxy_env_present': [k for k in os.environ if k.lower() in ('http_proxy','https_proxy','all_proxy','no_proxy')]}), flush=True)
    results = []
    for lang, voice, text in SAMPLES:
        started = time.monotonic()
        data = bytearray()
        result = {'variant': 'raw', 'language': lang, 'voice': voice}
        try:
            async def collect():
                async for item in edge_tts.Communicate(text, voice, connect_timeout=8, receive_timeout=10).stream():
                    if item['type'] == 'audio':
                        data.extend(item['data'])
            await asyncio.wait_for(collect(), 18)
            assert len(data) > 1000, f'Only {len(data)} speech bytes'
            path = ROOT / f'raw-{lang}.mp3'
            path.write_bytes(data)
            result.update(ok=True, bytes=len(data), artifact=path.name)
        except Exception as exc:
            headers = getattr(exc, 'headers', None) or {}
            result.update(ok=False, error=type(exc).__name__, status=getattr(exc, 'status', None),
                          response_headers={k: headers[k] for k in ('Date','Server','Retry-After') if k in headers})
        result['seconds'] = round(time.monotonic() - started, 3)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    (ROOT / 'raw-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(r['ok'] for r in results) else 1

if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
