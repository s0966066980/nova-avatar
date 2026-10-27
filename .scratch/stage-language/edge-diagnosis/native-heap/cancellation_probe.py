import asyncio
import json
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parents[3]))
os.chdir(ROOT)
from src.tts.engines import edge
from src.tts.base import State

class Emitter:
    instances=[]
    def __init__(self,*args,**kwargs):
        self.entered=threading.Event()
        self.release=threading.Event()
        self.finished_feed=threading.Event()
        self.active=0
        self.maximum=0
        self.finishes=0
        self.cancelled=False
        self.emitted=False
        self.emitted_samples=0
        self.trimmer=SimpleNamespace(onset_preroll_ms=0)
        Emitter.instances.append(self)
    def feed_mp3(self,data):
        self.active+=1
        self.maximum=max(self.maximum,self.active)
        self.entered.set()
        if not self.release.wait(3): raise TimeoutError('probe feed release missing')
        self.active-=1
        self.emitted=True
        self.emitted_samples=320
        self.finished_feed.set()
    def finish(self):
        self.active+=1
        self.maximum=max(self.maximum,self.active)
        self.finishes+=1
        self.active-=1

class Sink:
    def bind(self): pass
    async def wait_for_space(self): pass

async def source(*args):
    yield {'type':'audio','data':b'probe'}

async def run_case(path,cancel):
    if path=='synthesis':
        owner=edge.EdgeTTS(SimpleNamespace(audio=SimpleNamespace(fps=50)),SimpleNamespace())
        owner._open_edge_stream=source
        owner._record_onset_preroll=lambda emitter:None
        operation=owner._stream_with_retry('en-US-JennyNeural','probe',{},time.perf_counter(),frame_sink=Sink())
    else:
        operation=edge._prewarm_edge_tts('en-US-JennyNeural',decode_pcm=True,stream_factory=source)
    task=asyncio.create_task(operation)
    while not Emitter.instances or not Emitter.instances[-1].entered.is_set():
        await asyncio.sleep(.001)
    emitter=Emitter.instances[-1]
    if cancel:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
        still_running=not emitter.finished_feed.is_set()
        finishes_on_cancel=emitter.finishes
        emitter.release.set()
        await asyncio.to_thread(emitter.finished_feed.wait,2)
    else:
        still_running=False
        finishes_on_cancel=None
        emitter.release.set()
        await task
    result={'path':path,'cancel':cancel,'feed_still_running_when_coroutine_cancelled':still_running,
            'finish_calls_on_cancel':finishes_on_cancel,'finish_calls_total':emitter.finishes,
            'max_simultaneous_emitter_operations':emitter.maximum}
    assert emitter.maximum==1
    assert emitter.finishes==(0 if cancel else 1)
    Emitter.instances.clear()
    print(json.dumps(result),flush=True)
    return result

async def main():
    original=edge._EdgePCMEmitter
    edge._EdgePCMEmitter=Emitter
    try:
        results=[]
        for path in ('synthesis','prewarm'):
            for cancel in (False,True): results.append(await run_case(path,cancel))
    finally: edge._EdgePCMEmitter=original
    (ROOT/'cancellation-results.json').write_text(json.dumps(results,indent=2))

asyncio.run(main())
