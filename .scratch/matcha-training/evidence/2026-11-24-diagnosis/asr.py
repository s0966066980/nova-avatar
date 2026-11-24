# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
import sys, os, json, re, collections
os.environ["CUDA_VISIBLE_DEVICES"]=""
from faster_whisper import WhisperModel
from opencc import OpenCC
cc=OpenCC("t2s")
D=os.path.dirname(os.path.abspath(__file__))
m=WhisperModel("/home/oliver/nova-avatar/models/whisper-large-v3-turbo",device="cpu",compute_type="int8",cpu_threads=4)
meta=json.load(open(D+"/asr_meta.json"))
def norm(t): return re.sub(r"[\s，。？！、,.?!$:：;；'\"]","",cc.convert(t)).lower()
def reps(t): return collections.Counter(mm.group(1) for mm in re.finditer(r"(.{1,2}?)\1",t))
out=[]
for it in meta:
    segs,_=m.transcribe(it["file"],language="zh",beam_size=1,temperature=0.0,condition_on_previous_text=False,word_timestamps=True)
    segs=list(segs); hyp="".join(s.text for s in segs)
    words=[(w.word,round(w.start,2),round(w.end,2)) for s in segs for w in s.words]
    h=reps(norm(hyp)); r=reps(norm(it["ref"]))
    extra=sorted(c for c in h if c not in r and not c.isdigit() and not c.isascii())
    it.update(hyp=hyp,extra=extra,words=words); out.append(it)
    print(it["grp"],it["id"],it["rep"],"EXTRA" if extra else "ok",extra,hyp,flush=True)
    json.dump(out,open(D+"/asr_out.json","w"),ensure_ascii=False)
