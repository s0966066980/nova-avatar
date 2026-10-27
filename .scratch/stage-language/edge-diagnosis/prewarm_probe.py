import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parents[2]))
os.chdir(ROOT)
from src.tts.engines.edge import prewarm_edge_tts, shutdown_edge_tts

results=[]
try:
    for keep in (False,True):
        for voice in ('en-US-JennyNeural','zh-TW-HsiaoChenNeural'):
            started=time.monotonic()
            ready=prewarm_edge_tts(voice,timeout_seconds=18,decode_pcm=True,keep_connection=keep)
            result={'voice':voice,'keep_connection':keep,'decode_pcm':True,'ready':ready,'seconds':round(time.monotonic()-started,3)}
            results.append(result)
            print(json.dumps(result),flush=True)
finally:
    shutdown_edge_tts()
(ROOT/'prewarm-results.json').write_text(json.dumps(results,indent=2))
sys.exit(0 if all(r['ready'] for r in results) else 1)
