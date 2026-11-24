import sys, os, json
os.environ["CUDA_VISIBLE_DEVICES"]=""
sys.path.insert(0,"/home/oliver/nova-avatar")
import numpy as np, soundfile as sf, sherpa_onnx
import src.tts.engines.matcha as M
D=os.path.dirname(os.path.abspath(__file__))
H="/home/oliver/nova-avatar/models/tts/zh-tw-hsiaochen-edge/"; B="/home/oliver/nova-avatar/models/tts/matcha-icefall-zh-en/"
refs=json.load(open(D+"/refs.json"))
bad=["tw-reading-16","tw-reading-17","tw-reading-23","number-20","general-13","general-03","place-01","tw-reading-15","tw-reading-18","general-07","tw-reading-14","place-16"]
good=["tw-reading-01","tw-reading-02","tw-reading-03","tw-reading-04","tw-reading-05","tw-reading-06","tw-reading-07","place-02","place-03","general-01","general-04","general-05"]
fsts=",".join(B+n for n in ("phone-zh.fst","date-zh.fst","number-zh.fst"))
cfgs={"B_hsiaoModel_baseLex":(H+"model.onnx",B+"lexicon.txt"),"C_baseModel_hsiaoLex":(B+"model-steps-3.onnx",H+"lexicon.txt"),"D_baseModel_baseLex":(B+"model-steps-3.onnx",B+"lexicon.txt")}
conv=M._build_t2s_converter()
meta=[]
for name,(am,lex) in cfgs.items():
    c=sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(matcha=sherpa_onnx.OfflineTtsMatchaModelConfig(acoustic_model=am,vocoder=H+"vocos-16khz-univ.onnx",lexicon=lex,tokens=H+"tokens.txt",noise_scale=0.667,length_scale=1.0),num_threads=4,provider="cpu"),rule_fsts=fsts,max_num_sentences=1)
    assert c.validate()
    tts=sherpa_onnx.OfflineTts(c); words=M.load_lexicon_words(lex)
    os.makedirs(f"{D}/abl/{name}",exist_ok=True)
    for grp,ids,reps in (("bad",bad,2),("good",good,1)):
        for i in ids:
            for r in range(reps):
                g=tts.generate(M.normalize_matcha_text(refs[i],lexicon_words=words,converter=conv),sid=0,speed=1.0)
                x=np.asarray(g.samples,dtype=np.float32); x=x*(0.88/abs(x).max()) if abs(x).max()>0.88 else x
                fn=f"{D}/abl/{name}/{grp}_{i}_{r}.wav"; sf.write(fn,x,16000)
                meta.append(dict(cfg=name,grp=grp,id=i,rep=r,file=fn,ref=refs[i]))
json.dump(meta,open(D+"/abl_meta.json","w"),ensure_ascii=False); print(len(meta))
