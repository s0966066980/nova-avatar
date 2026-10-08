# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Actual GGUF -> production OpenAILLM -> protocol, without avatar/TTS load."""
import argparse,json,sys,time
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path.cwd()))
from src.config.loader import load_config
from src.llm.llamacpp import ensure_server
from src.llm.engines.openai import OpenAILLM
from src.llm.router import ReplyMode
from src.llm.response_protocol import clean_speech_text,FORMAT_RECOVERY_MESSAGE
QUESTIONS=['你好！請簡短自我介紹','請整理 Nova Avatar 三大核心技術優勢並輸出看板','請列出系統安裝部署四步驟','今天台北天氣如何？']
class RecordingStream:
 def __init__(self,stream,record,start):self.stream=stream;self.record=record;self.start=start
 def __iter__(self):
  for chunk in self.stream:
   if chunk.choices:
    choice=chunk.choices[0];delta=choice.delta
    content=getattr(delta,'content',None) or '';reasoning=getattr(delta,'reasoning_content',None) or ''
    if (content or reasoning) and self.record['first_token_seconds'] is None:self.record['first_token_seconds']=time.perf_counter()-self.start
    if content and self.record['first_content_seconds'] is None:self.record['first_content_seconds']=time.perf_counter()-self.start
    self.record['raw_content']+=content;self.record['raw_reasoning']+=reasoning
    if choice.finish_reason:self.record['finish_reason']=choice.finish_reason
   extra=getattr(chunk,'model_extra',{}) or {}
   if extra.get('timings'):self.record['timings']=extra['timings']
   if chunk.usage:self.record['usage']=chunk.usage.model_dump()
   yield chunk
 def close(self):self.stream.close()
class Recorder:
 def __init__(self,client):self.client=client;self.chat=SimpleNamespace(completions=self);self.record=None
 def create(self,**kwargs):return RecordingStream(self.client.chat.completions.create(**kwargs),self.record,time.perf_counter())
args=argparse.ArgumentParser();args.add_argument('--output',default='.scratch/lfm-resolution/model-before.json');args.add_argument('--rounds',type=int,default=2);args.add_argument('--keep-alive',action='store_true');args.add_argument('--reasoning',choices=['on','off']);args.add_argument('--budget',type=int);args.add_argument('--temperature',type=float);args.add_argument('--compact',action='store_true');args.add_argument('--grammar',action='store_true');args.add_argument('--repeat-penalty',type=float);args=args.parse_args()
if args.reasoning is not None or args.budget is not None:
 import src.llm.llamacpp as launcher
 popen=launcher.subprocess.Popen
 def launch(command,*pos,**kw):
  if isinstance(command,list) and command and str(command[0]).endswith('llama-server'):
   command=list(command)
   if args.reasoning is not None:command[command.index('--reasoning')+1]=args.reasoning
   if args.budget is not None:command[command.index('--reasoning-budget')+1]=str(args.budget)
  return popen(command,*pos,**kw)
 launcher.subprocess.Popen=launch
if args.compact:
 import src.llm.base as base
 from src.llm.prompts import AUTO_MODE_PROMPT,CHANNEL_SPLIT_PROMPT
 original=base.compose_system_prompt
 compact=Path('.scratch/lfm-resolution/compact-protocol.txt').read_text()
 def compose(*pos,**kw):return original(*pos,**kw).replace(AUTO_MODE_PROMPT,compact).replace(CHANNEL_SPLIT_PROMPT,'')
 base.compose_system_prompt=compose
c=load_config('config/config_jetson.yaml')
c.llm.base_url=ensure_server(c.llm.model,extra_dir=c.llm.llamacpp_dir,ctx=c.llm.llamacpp_ctx,threads=c.llm.llamacpp_threads)
if args.temperature is not None:c.llm.extra_body={**c.llm.extra_body,'temperature':args.temperature}
if args.repeat_penalty is not None:c.llm.extra_body={**c.llm.extra_body,'repeat_penalty':args.repeat_penalty}
if args.grammar:c.llm.extra_body={**c.llm.extra_body,'grammar':Path('.scratch/lfm-resolution/protocol.gbnf').read_text()}
e=OpenAILLM(c,api_key=c.llm.api_key,base_url=c.llm.base_url,model=c.llm.model)
rec=Recorder(e.client);e._client=rec
rows=[]
for run in range(args.rounds):
 e.clear_history()
 for q in QUESTIONS:
  row={'round':run+1,'question':q,'raw_content':'','raw_reasoning':'','first_token_seconds':None,'first_content_seconds':None,'finish_reason':None,'modes':[],'boards':[]}
  rec.record=row;start=time.perf_counter()
  try:
   row['speech']=e.generate_response(q,stream_to_avatar=False,reply_mode=ReplyMode.AUTO,datainfo={'on_mode':lambda m:row['modes'].append(str(m)),'on_board':lambda b:row['boards'].append(b)})
   row['playable_speech']=clean_speech_text(row['speech']).strip()
   row['has_board']=bool(row['boards'])
   row['item_count']=len(row['boards'][-1].get('items',[])) if row['boards'] else 0
   row['pass']=bool(row['playable_speech']) and row['playable_speech']!=FORMAT_RECOVERY_MESSAGE and (row['has_board'] if '看板' in q or '四步驟' in q else True) and (row['item_count']==4 if '四步驟' in q else row['item_count']==3 if '三大' in q else True)
  except Exception as ex:row['error']=type(ex).__name__;row['pass']=False
  row['total_seconds']=time.perf_counter()-start;rows.append(row)
  Path(args.output).write_text(json.dumps({'model':c.llm.model,'max_tokens':e.max_tokens,'rows':rows,'pass':all(r['pass'] for r in rows)},ensure_ascii=False,indent=2)+'\n')
  print(json.dumps({k:v for k,v in row.items() if k not in ['raw_content','raw_reasoning','boards']},ensure_ascii=False),flush=True)
if args.keep_alive:
 print('MODEL_PROBE_DONE_KEEP_ALIVE',flush=True)
 while True:time.sleep(1)
assert all(r['pass'] for r in rows),'Example question produced no playable response'
